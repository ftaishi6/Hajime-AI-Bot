"""basics 1 件を生成 → #hajime-basics に投下 → basics_history に記録。

cron (毎日 12:00 JST) と手動 /hjm-basics の両方から呼ぶ。

配信フォーマット(Embed 1 つ):
  title:       📚 今日の AI 基礎用語: {term} ({en})
  url:         タップで X 投稿画面が開く (Web Intent, text pre-fill)
  description: 本文 + 字数表示
  footer:      Tier {tier} · term_id={term_id}
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse

import discord

from . import generator, repo, selector

log = logging.getLogger("hajime-ai-bot.basics.dispatcher")

X_INTENT_BASE = "https://x.com/intent/tweet"


def _build_intent_url(text: str) -> str:
    qs = urllib.parse.urlencode({"text": text}, quote_via=urllib.parse.quote)
    return f"{X_INTENT_BASE}?{qs}"


def _resolve_channel_id() -> int | None:
    raw = os.environ.get("DISCORD_CHANNEL_BASICS")
    if not raw:
        log.error("DISCORD_CHANNEL_BASICS が未設定。配信スキップ。")
        return None
    try:
        return int(raw)
    except ValueError:
        log.error("DISCORD_CHANNEL_BASICS が数値でない: %r", raw)
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
        log.error("basics 配信先チャンネル %d を取得できません: %s", channel_id, e)
        return None


async def generate_and_dispatch(
    bot: discord.Client,
    *,
    trigger: str,
    term_id: int | None = None,
) -> bool:
    """basics 1 件を生成 → #hajime-basics に投下 → DB 記録。

    Parameters
    ----------
    term_id : int | None
        指定があればその用語を強制。None なら selector が自動選定。

    Returns
    -------
    bool
        配信に成功したら True。
    """
    channel_id = _resolve_channel_id()
    if channel_id is None:
        return False
    channel = await _get_channel(bot, channel_id)
    if channel is None:
        return False

    # 1. 用語選定
    try:
        if term_id is None:
            term = await asyncio.to_thread(selector.pick_next_term)
        else:
            term = await asyncio.to_thread(selector.get_term_by_id, term_id)
    except selector.SelectorError as e:
        log.warning("basics dispatcher: select failed: %s", e)
        await channel.send(f"⚠ 用語選定に失敗しました\n```{e}```")
        return False

    # 2. Claude で本文生成
    try:
        result = await asyncio.to_thread(generator.generate_basics, term)
    except generator.GeneratorError as e:
        log.warning(
            "basics dispatcher: generate failed for term=%s: %s",
            term.get("term"), e,
        )
        await channel.send(
            f"⚠ 基礎用語『{term.get('term')}』の生成に失敗しました\n```{e}```"
        )
        return False

    # 3. Embed 構築 + 配信
    intent_url = _build_intent_url(result.text)
    char_marker = (
        f"⚠ **{len(result.text)}字 (140 超過、短縮要)**"
        if result.over_limit
        else f"{len(result.text)}字"
    )
    embed = discord.Embed(
        title=f"📚 今日の AI 基礎用語: {result.term} ({result.en})",
        url=intent_url,
        description=(
            f"{result.text}\n\n— *{char_marker}・タップで X 投稿画面*"
        ),
        color=discord.Color.from_rgb(46, 204, 113),
    )
    embed.set_footer(
        text=f"Tier {result.tier} · term_id={result.term_id} · trigger={trigger}"
    )
    sent = await channel.send(embed=embed)

    # 4. DB に履歴記録
    try:
        await asyncio.to_thread(
            repo.insert_history,
            term_id=result.term_id,
            term=result.term,
            generated_text=result.text,
            discord_message_id=str(sent.id) if sent else None,
        )
    except Exception:
        log.exception("basics dispatcher: insert_history failed")

    log.info(
        "basics dispatch done: term_id=%d term=%s trigger=%s (over=%s)",
        result.term_id, result.term, trigger, result.over_limit,
    )
    return True
