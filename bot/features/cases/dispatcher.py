"""cases 配信ワーカー: 1 件 pickup → 3 パターン生成 → #hajime-cases に投下。

cron (火曜 09:00 JST) と手動 /hjm-case-post-now の両方から呼ぶ。

配信フォーマット(1 メッセージ・複数 Embed):
  Embed 1: 事例サマリ(title / 課題 / 実装 / 成果 / 出典)
  Embed 2: 📖 story 案 (タップで X 投稿画面)
  Embed 3: 📊 numbers 案
  Embed 4: 🪞 introspection 案
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
from dataclasses import asdict

import discord

from . import generator, repo

log = logging.getLogger("hajime-ai-bot.cases.dispatcher")

X_INTENT_BASE = "https://x.com/intent/tweet"

PATTERN_META = {
    "story":         ("📖 ストーリー型", discord.Color.from_rgb(52, 152, 219)),
    "numbers":       ("📊 数字インパクト型", discord.Color.from_rgb(46, 204, 113)),
    "introspection": ("🪞 内省型(俺でもできた)", discord.Color.from_rgb(155, 89, 182)),
}


def _build_intent_url(text: str, *, append_url: str | None = None) -> str:
    """X 投稿画面に text を pre-fill する URL。

    append_url を渡すと URL を末尾に付与(X カードプレビューが展開される)。
    """
    params: dict[str, str] = {"text": text}
    if append_url:
        params["url"] = append_url
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{X_INTENT_BASE}?{qs}"


def _resolve_channel_id() -> int | None:
    raw = os.environ.get("DISCORD_CHANNEL_CASES")
    if not raw:
        log.error("DISCORD_CHANNEL_CASES が未設定。配信スキップ。")
        return None
    try:
        return int(raw)
    except ValueError:
        log.error("DISCORD_CHANNEL_CASES が数値でない: %r", raw)
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
        log.error("cases 配信先チャンネル %d を取得できません: %s", channel_id, e)
        return None


async def generate_and_dispatch(
    bot: discord.Client,
    *,
    trigger: str,
    case_id: int | None = None,
) -> bool:
    """case 1 件を pickup → 3 パターン生成 → #hajime-cases に投下 → DB 記録。

    Parameters
    ----------
    case_id : int | None
        指定があればその case を強制。None なら未配信を自動選定。

    Returns
    -------
    bool : 配信に成功したら True。
    """
    channel_id = _resolve_channel_id()
    if channel_id is None:
        return False
    channel = await _get_channel(bot, channel_id)
    if channel is None:
        return False

    # 1. case 選定
    if case_id is None:
        case = await asyncio.to_thread(repo.pick_next_unposted_case)
        if case is None:
            await channel.send(
                "📭 配信できる事例(status=active)がありません。"
                " #hajime-case-input に事例を登録してください。"
            )
            return False
    else:
        case = await asyncio.to_thread(repo.get_case, case_id)
        if case is None:
            await channel.send(f"❌ case_id={case_id} が見つかりません")
            return False
        if case.get("status") != "active":
            await channel.send(
                f"⚠ case_id={case_id} は status={case.get('status')} です(配信続行)"
            )

    # 2. 3 パターン生成
    try:
        result = await asyncio.to_thread(generator.generate_patterns, case)
    except generator.GeneratorError as e:
        log.warning(
            "cases dispatcher: generate failed for case_id=%s: %s", case["id"], e
        )
        await channel.send(
            f"⚠ 事例『{case.get('title')}』の生成に失敗しました\n```{e}```"
        )
        return False

    # 3. Embed 群を組み立てて 1 メッセージで送る
    embeds = _build_embeds(case, result)
    sent = await channel.send(embeds=embeds)

    # 4. DB 記録
    try:
        await asyncio.to_thread(
            repo.insert_case_post,
            case_id=result.case_id,
            trigger=trigger,
            generated_patterns=[asdict(p) for p in result.patterns],
            discord_message_id=str(sent.id) if sent else None,
            model=result.model,
        )
    except Exception:
        log.exception("cases dispatcher: insert_case_post failed")

    log.info(
        "cases dispatch done: case_id=%d title=%s trigger=%s patterns=%d",
        result.case_id, case.get("title"), trigger, len(result.patterns),
    )
    return True


def _build_embeds(case: dict, result: generator.GeneratedCasePost) -> list[discord.Embed]:
    """事例サマリ + 3 パターン Embed を返す(最大 4 Embed)。"""
    embeds: list[discord.Embed] = []

    # Embed 1: 事例サマリ
    summary = discord.Embed(
        title=f"💼 自社内製事例: {case.get('title', '(無題)')}",
        url=case.get("source_url") or None,
        color=discord.Color.from_rgb(231, 76, 60),
    )
    if case.get("challenge"):
        summary.add_field(
            name="🎯 課題", value=case["challenge"][:1000], inline=False
        )
    if case.get("implementation"):
        summary.add_field(
            name="🔧 実装", value=case["implementation"][:1000], inline=False
        )
    if case.get("outcome"):
        summary.add_field(
            name="✨ 成果", value=case["outcome"][:1000], inline=False
        )
    if case.get("impact_numbers"):
        summary.add_field(
            name="📈 数字", value=case["impact_numbers"][:200], inline=True
        )
    if case.get("period"):
        summary.add_field(
            name="🗓 期間", value=case["period"][:100], inline=True
        )
    footer_bits = [f"case_id={case['id']}"]
    if case.get("source_url"):
        footer_bits.append("出典 URL あり(タイトルをタップ)")
    summary.set_footer(text=" · ".join(footer_bits))
    embeds.append(summary)

    # Embed 2-4: 各パターン
    for p in result.patterns:
        title_emoji, color = PATTERN_META.get(
            p.pattern, (f"📝 {p.pattern}", discord.Color.greyple())
        )
        marker = (
            f"⚠ **{p.chars}字 (140 超過、短縮要)**"
            if p.over_limit else f"{p.chars}字"
        )
        # source_url がある事例は X 投稿時に URL を末尾付与して「カード展開」させる。
        intent_url = _build_intent_url(
            p.text,
            append_url=case.get("source_url") or None,
        )
        embed = discord.Embed(
            title=title_emoji,
            url=intent_url,
            description=(
                f"{p.text}\n\n— *{marker}・タップで X 投稿画面*"
            ),
            color=color,
        )
        embeds.append(embed)

    return embeds
