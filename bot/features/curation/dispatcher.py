"""curation digest → #hajime-curation に Embed 投下する共通ワーカー。

cron (毎日 07:00 JST) と手動 /hjm-curate の両方から呼ぶ。

配信フォーマット(各 highlight = 2 Embed):
  1) 元投稿 Embed(タップで X 元投稿へ)
  2) 💬 引用 RT 案 Embed(タップで X intent: text + url=元投稿URL → quote tweet 風)
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse

import discord

from . import digester, repo

log = logging.getLogger("hajime-ai-bot.curation.dispatcher")

X_INTENT_BASE = "https://x.com/intent/tweet"


def _build_intent_url(text: str, *, quote_url: str | None = None) -> str:
    """X 投稿画面に text を pre-fill する URL。

    quote_url を渡すと URL を末尾に付与(X UI は元投稿のカードプレビューを展開)。
    Web Intent は厳密な quote tweet を作れないが、これが代替となる挙動。
    """
    params: dict[str, str] = {"text": text}
    if quote_url:
        params["url"] = quote_url
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{X_INTENT_BASE}?{qs}"


def _resolve_channel_id() -> int | None:
    raw = os.environ.get("DISCORD_CHANNEL_CURATION")
    if not raw:
        log.error("DISCORD_CHANNEL_CURATION が未設定。配信スキップ。")
        return None
    try:
        return int(raw)
    except ValueError:
        log.error("DISCORD_CHANNEL_CURATION が数値でない: %r", raw)
        return None


async def _get_channel(
    bot: discord.Client, channel_id: int
) -> discord.abc.Messageable | None:
    ch = bot.get_channel(channel_id)
    if ch is not None:
        return ch
    try:
        return await bot.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden) as e:
        log.error("curation 配信先チャンネル %d を取得できません: %s", channel_id, e)
        return None


async def run_and_dispatch(
    bot: discord.Client, *, trigger: str
) -> tuple[int, int]:
    """curation を 1 回実行して #hajime-curation に投下する。

    Returns (highlights_count, accounts_scanned)
    """
    channel_id = _resolve_channel_id()
    if channel_id is None:
        return (0, 0)
    channel = await _get_channel(bot, channel_id)
    if channel is None:
        return (0, 0)

    try:
        result = await asyncio.to_thread(digester.run_curation)
    except digester.CurationError as e:
        log.warning("curation dispatcher: digest failed: %s", e)
        await channel.send(f"⚠ キュレーション実行に失敗しました\n```{e}```")
        return (0, 0)

    try:
        await asyncio.to_thread(
            repo.insert_curation_run,
            trigger=trigger,
            accounts_scanned=result.accounts_scanned,
            tweets_fetched=result.tweets_fetched,
            highlights_count=len(result.highlights),
            model=digester.DEFAULT_MODEL,
            notes="; ".join(result.errors)[:500] if result.errors else None,
        )
    except Exception:
        log.exception("curation dispatcher: insert_curation_run failed")

    err_suffix = (
        f"  ⚠ {len(result.errors)} 件取得エラー" if result.errors else ""
    )
    header = (
        f"📡 **今日の AI バズキュレーション** (trigger=`{trigger}`)\n"
        f"対象 **{result.accounts_scanned}** アカウント / "
        f"バズ投稿 **{result.tweets_fetched}** 件 / "
        f"抽出 **{len(result.highlights)}** highlight{err_suffix}"
    )
    await channel.send(header)

    if result.tweets_fetched == 0:
        await channel.send(
            "(直近 24h で `min_likes` を超えるバズ投稿はありませんでした。"
            "閾値は `config.yaml` の `curation.min_likes` で調整できます)"
        )
        return (0, result.accounts_scanned)

    if not result.highlights:
        await channel.send(
            "(バズ投稿はありましたが、Claude が古谷さん文脈で気になるものを抽出しませんでした)"
        )
        return (0, result.accounts_scanned)

    for i, hl in enumerate(result.highlights, start=1):
        try:
            await _deliver_one(channel, hl, idx=i, total=len(result.highlights))
        except Exception:
            log.exception(
                "curation dispatcher: deliver failed for tweet_id=%s", hl.tweet_id
            )

    log.info(
        "curation dispatch done: accounts=%d tweets=%d highlights=%d trigger=%s",
        result.accounts_scanned, result.tweets_fetched, len(result.highlights), trigger,
    )
    return (len(result.highlights), result.accounts_scanned)


async def _deliver_one(
    channel: discord.abc.Messageable,
    hl: digester.CurationHighlight,
    *,
    idx: int,
    total: int,
) -> None:
    """1 つの highlight を 2 Embed で投下(元投稿 + 引用 RT 案)。"""
    body = hl.text
    if len(body) > 500:
        body = body[:495] + "…"

    handle_clean = (hl.author_handle or "").lstrip("@").strip()

    # Embed 1: 元投稿
    embed_src = discord.Embed(
        title=f"@{handle_clean}",
        url=hl.url,
        description=body,
        color=discord.Color.from_rgb(29, 161, 242),  # X 色
    )
    embed_src.add_field(
        name="💡 なぜ古谷さん文脈で気になるか",
        value=(hl.why_relevant or "(なし)")[:1000],
        inline=False,
    )
    embed_src.set_footer(
        text=(
            f"highlight {idx}/{total} · "
            f"❤{hl.like_count} 🔁{hl.retweet_count} 💬{hl.reply_count} · "
            f"tweet_id={hl.tweet_id}"
        )
    )

    embeds: list[discord.Embed] = [embed_src]

    # Embed 2: 引用 RT 案(text + url=元投稿)
    quote = (hl.quote_draft or "").strip()
    if quote:
        intent_url = _build_intent_url(quote, quote_url=hl.url)
        qlen = len(quote)
        marker = (
            f"⚠ **{qlen}字 (140 超過、短縮要)**" if qlen > 140 else f"{qlen}字"
        )
        embeds.append(
            discord.Embed(
                title="💬 引用 RT 案",
                url=intent_url,
                description=(
                    f"{quote}\n\n"
                    f"— *{marker}・タップで X 投稿画面*\n"
                    f"— *(X 側で元投稿が URL カードとして展開される)*"
                ),
                color=discord.Color.from_rgb(255, 153, 0),
            )
        )

    await channel.send(embeds=embeds)
