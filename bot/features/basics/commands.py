"""/hjm-basics スラッシュコマンド。

  /hjm-basics                  今すぐ自動選定で 1 件生成 → #hajime-basics
  /hjm-basics term_id:5        ID 指定で生成
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from . import dispatcher, repo

log = logging.getLogger("hajime-ai-bot.basics.commands")


def setup(bot: discord.Client) -> None:
    @bot.tree.command(
        name="hjm-basics",
        description="今すぐ AI 基礎用語解説を 1 件生成 → #hajime-basics に投下",
    )
    @app_commands.describe(
        term_id="使う用語の ID(persona.yaml の basics_catalog)。省略時は自動選定",
    )
    async def hjm_basics(
        interaction: discord.Interaction, term_id: int | None = None
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        ok = await dispatcher.generate_and_dispatch(
            interaction.client, trigger="manual", term_id=term_id
        )
        if ok:
            msg = "✅ 基礎用語解説を #hajime-basics に投下しました。"
        else:
            msg = "⚠ 配信に失敗しました。詳細は #hajime-system-logs を確認してください。"
        await interaction.followup.send(msg, ephemeral=True)

    @bot.tree.command(
        name="hjm-basics-history",
        description="直近の basics 配信履歴(最新 10 件)",
    )
    async def hjm_basics_history(interaction: discord.Interaction) -> None:
        recent = await asyncio.to_thread(repo.list_recent, 10)
        total = await asyncio.to_thread(repo.count)
        if not recent:
            await interaction.response.send_message(
                f"📭 basics_history は空です(累計 {total} 件)", ephemeral=True
            )
            return
        lines = [f"📚 **basics 直近配信** (累計 {total} 件)\n"]
        for r in recent:
            preview = (r.get("generated_text") or "")[:40].replace("\n", " ")
            lines.append(
                f"  {r['posted_at']} id={r['term_id']:>2} {r['term']:>18} | {preview}…"
            )
        msg = "\n".join(lines)
        if len(msg) > 1990:
            msg = msg[:1980] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    log.info("registered /hjm-basics and /hjm-basics-history commands")
