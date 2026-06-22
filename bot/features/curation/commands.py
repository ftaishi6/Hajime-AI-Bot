"""/hjm-curate / /hjm-watch スラッシュコマンド群。

  /hjm-curate                  今すぐキュレーション実行 → #hajime-curation
  /hjm-watch list              watchlist + 直近 5 件の実行履歴
  /hjm-watch add @handle       watchlist に追加(X API で存在確認)
  /hjm-watch remove @handle    status を paused に
  /hjm-watch sync              config.yaml の watch_accounts を DB と再 sync
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
import yaml
from discord import app_commands

from . import dispatcher, repo, x_client

log = logging.getLogger("hajime-ai-bot.curation.commands")

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config.yaml"


def setup(bot: discord.Client) -> None:
    @bot.tree.command(
        name="hjm-curate",
        description="今すぐ AI バズキュレーションを実行して #hajime-curation に投下",
    )
    async def hjm_curate(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        highlights, scanned = await dispatcher.run_and_dispatch(
            interaction.client, trigger="manual"
        )
        await interaction.followup.send(
            f"✅ curation 完了: {scanned} アカウント / {highlights} highlight。"
            f" 詳細は #hajime-curation を確認してください。",
            ephemeral=True,
        )

    group = app_commands.Group(
        name="hjm-watch", description="AI 系発信者の watchlist 管理"
    )

    @group.command(name="add", description="watchlist に @handle を追加(X 存在確認あり)")
    @app_commands.describe(
        handle="X ユーザー名(@ は付けても付けなくても OK)",
        notes="メモ(任意、なぜ watch するか等)",
    )
    async def watch_add(
        interaction: discord.Interaction, handle: str, notes: str | None = None
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        handle = handle.lstrip("@").strip()
        if not handle:
            await interaction.followup.send("❌ handle が空です", ephemeral=True)
            return
        try:
            user_ref = await asyncio.to_thread(x_client.lookup_user, handle)
        except x_client.XClientError as e:
            log.warning("hjm-watch add: lookup failed @%s: %s", handle, e)
            await interaction.followup.send(
                f"❌ @{handle} が見つかりません or X API エラー\n```{e}```",
                ephemeral=True,
            )
            return
        _, is_new = await asyncio.to_thread(
            repo.upsert_account,
            user_ref.handle,
            source="manual",
            notes=notes,
            display_name=user_ref.display_name,
            user_id=user_ref.user_id,
        )
        action = "追加" if is_new else "更新"
        await interaction.followup.send(
            f"✅ @{user_ref.handle} ({user_ref.display_name}) を watchlist に{action}しました",
            ephemeral=True,
        )

    @group.command(name="list", description="watchlist + 直近 5 件のキュレーション実行履歴")
    async def watch_list(interaction: discord.Interaction) -> None:
        accts = await asyncio.to_thread(repo.list_all)
        runs = await asyncio.to_thread(repo.list_recent_runs, 5)

        if not accts:
            await interaction.response.send_message(
                "📭 watchlist が空です。`config.yaml` の `watch_accounts` または "
                "`/hjm-watch add @handle` で追加してください。",
                ephemeral=True,
            )
            return

        lines = ["📡 **watchlist (AI 系)**\n"]
        for a in accts:
            name = a.get("display_name") or "(未取得)"
            uid = a.get("user_id") or "?"
            last = a.get("last_fetched_at") or "-"
            notes = (a.get("notes") or "").strip()
            note_str = f" · {notes[:30]}" if notes else ""
            lines.append(
                f"`#{a['id']:2}` @{a['handle']:20} [{a['status']:6}] "
                f"src={a['source']:6} uid={uid:>16} last={last}{note_str}"
            )

        lines.append("\n📊 **直近キュレーション実行**")
        if not runs:
            lines.append("(まだ実行履歴がありません)")
        else:
            for r in runs:
                lines.append(
                    f"  {r['run_at']} {r['trigger']:11} "
                    f"accts={r['accounts_scanned']} tweets={r['tweets_fetched']} "
                    f"hl={r['highlights_count']}"
                )

        msg = "\n".join(lines)
        if len(msg) > 1990:
            msg = msg[:1980] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="remove", description="watchlist の @handle を paused に")
    @app_commands.describe(handle="X ユーザー名")
    async def watch_remove(interaction: discord.Interaction, handle: str) -> None:
        handle = handle.lstrip("@").strip()
        n = await asyncio.to_thread(repo.update_status, handle, "paused")
        if n == 0:
            await interaction.response.send_message(
                f"❌ @{handle} は watchlist にありません", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"⏸ @{handle} を paused に変更しました", ephemeral=True
        )

    @group.command(name="sync", description="config.yaml の watch_accounts を DB と再 sync")
    async def watch_sync(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            entries = _load_config_watch_accounts()
        except Exception as e:
            await interaction.followup.send(
                f"❌ config.yaml 読み込み失敗\n```{e}```", ephemeral=True
            )
            return
        added, kept = await asyncio.to_thread(repo.sync_from_config, entries)
        await interaction.followup.send(
            f"✅ sync 完了: 新規追加 **{added} 件** / 既存 **{kept} 件**\n"
            f"(削除はしません。完全停止は `/hjm-watch remove`)",
            ephemeral=True,
        )

    bot.tree.add_command(group)
    log.info("registered /hjm-curate command and /hjm-watch group")


def _load_config_watch_accounts() -> list[dict]:
    if not _CONFIG_PATH.exists():
        return []
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("watch_accounts", [])
    if not isinstance(entries, list):
        return []
    return entries
