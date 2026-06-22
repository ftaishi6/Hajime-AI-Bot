"""#hajime-case-input チャンネルへの投稿を監視し、自動取り込み + 構造化。

main.py の on_message から呼ばれる。Bot 自身のメッセージ・他チャンネル・
コマンド類は弾く。Claude 抽出に時間がかかるので thinking リアクションを
先に付け、完了で ✅、失敗で ❌ を残す。
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord

from . import extractor, repo

log = logging.getLogger("hajime-ai-bot.cases.message_handler")

MIN_CONTENT_LEN = 20  # これ未満の投稿は事例として扱わない(短すぎてノイズ)


def _resolve_input_channel_id() -> int | None:
    raw = os.environ.get("DISCORD_CHANNEL_CASE_INPUT")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log.error("DISCORD_CHANNEL_CASE_INPUT が数値でない: %r", raw)
        return None


async def handle_message(bot: discord.Client, message: discord.Message) -> None:
    """on_message から呼び出す。対象外メッセージは即 return。"""
    if message.author.bot:
        return
    input_channel_id = _resolve_input_channel_id()
    if input_channel_id is None:
        return
    if message.channel.id != input_channel_id:
        return

    content = (message.content or "").strip()
    if not content:
        return
    if len(content) < MIN_CONTENT_LEN:
        try:
            await message.reply(
                f"⚠ 事例として取り込むには本文が短すぎます({len(content)} / 必要 {MIN_CONTENT_LEN} 字以上)。"
                "もう少し詳しく書いてください 🙏",
                mention_author=False,
            )
        except Exception:
            log.exception("cases handler: short-msg reply failed")
        return

    # 二重 import 防止
    if await asyncio.to_thread(repo.already_imported, str(message.id)):
        log.info("cases handler: message %s already imported, skip", message.id)
        return

    # 受領サイン
    try:
        await message.add_reaction("⏳")
    except Exception:
        log.exception("cases handler: add_reaction(⏳) failed")

    # Claude で構造化
    try:
        extracted = await asyncio.to_thread(extractor.extract_case, content)
    except extractor.ExtractorError as e:
        log.warning("cases handler: extract failed for msg=%s: %s", message.id, e)
        try:
            await message.remove_reaction("⏳", bot.user)
        except Exception:
            pass
        try:
            await message.add_reaction("❌")
        except Exception:
            pass
        try:
            await message.reply(
                f"❌ 構造化に失敗しました\n```{e}```\n"
                "事例として読み取れない場合は、課題 / 実装 / 成果 を含めて書き直してください 🙏",
                mention_author=False,
            )
        except Exception:
            log.exception("cases handler: failure reply failed")
        return

    # DB insert
    try:
        case_id = await asyncio.to_thread(
            repo.insert_case,
            title=extracted.title,
            raw_text=content,
            challenge=extracted.challenge,
            implementation=extracted.implementation,
            outcome=extracted.outcome,
            impact_numbers=extracted.impact_numbers,
            source_url=extracted.source_url,
            period=extracted.period,
            discord_message_id=str(message.id),
            discord_channel_id=str(message.channel.id),
            discord_author_id=str(message.author.id),
            extraction_model=extracted.model,
        )
    except Exception as e:
        log.exception("cases handler: insert_case failed for msg=%s", message.id)
        try:
            await message.remove_reaction("⏳", bot.user)
        except Exception:
            pass
        try:
            await message.add_reaction("❌")
        except Exception:
            pass
        try:
            await message.reply(
                f"❌ DB 保存に失敗しました\n```{e}```", mention_author=False
            )
        except Exception:
            pass
        return

    # 成功通知 + 確認サマリ
    try:
        await message.remove_reaction("⏳", bot.user)
    except Exception:
        pass
    try:
        await message.add_reaction("✅")
    except Exception:
        pass

    summary_lines = [
        f"✅ **事例 #{case_id}** を登録しました",
        f"**タイトル**: {extracted.title}",
    ]
    if extracted.challenge:
        summary_lines.append(f"**課題**: {extracted.challenge[:120]}")
    if extracted.implementation:
        summary_lines.append(f"**実装**: {extracted.implementation[:120]}")
    if extracted.outcome:
        summary_lines.append(f"**成果**: {extracted.outcome[:120]}")
    if extracted.impact_numbers:
        summary_lines.append(f"**数字**: {extracted.impact_numbers}")
    if extracted.source_url:
        summary_lines.append(f"**出典**: {extracted.source_url}")
    if extracted.period:
        summary_lines.append(f"**期間**: {extracted.period}")
    summary_lines.append(
        "\n次の火曜 09:00 JST に自動配信されます。今すぐ確認したい場合は "
        f"`/hjm-case-post-now case_id:{case_id}` を使ってください。"
    )
    try:
        await message.reply("\n".join(summary_lines), mention_author=False)
    except Exception:
        log.exception("cases handler: success reply failed")
