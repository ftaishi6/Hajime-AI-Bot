"""/hjm-case-list / /hjm-case-post-now / /hjm-case-show スラッシュコマンド。

事例の自由文登録は #hajime-case-input への投稿が一次入口なので、
スラッシュコマンドは「閲覧・配信トリガ」に絞る。
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from . import dispatcher, git_sync, repo

log = logging.getLogger("hajime-ai-bot.cases.commands")


def setup(bot: discord.Client) -> None:
    @bot.tree.command(
        name="hjm-case-list",
        description="登録済み事例 + 直近の配信履歴を表示",
    )
    async def hjm_case_list(interaction: discord.Interaction) -> None:
        cases = await asyncio.to_thread(repo.list_active)
        posts = await asyncio.to_thread(repo.list_recent_posts, 5)
        last_posted = await asyncio.to_thread(repo.last_posted_at_by_case)

        if not cases:
            await interaction.response.send_message(
                "📭 active な事例がありません。`#hajime-case-input` に投稿して登録してください。",
                ephemeral=True,
            )
            return

        lines = [f"💼 **登録済み事例 ({len(cases)} 件)**\n"]
        for c in cases:
            last = last_posted.get(int(c["id"]), "未配信")
            title = (c.get("title") or "(無題)")[:40]
            period = c.get("period") or "-"
            impact = c.get("impact_numbers") or ""
            extra = f" · {impact}" if impact else ""
            lines.append(
                f"  `#{c['id']:>2}` {title:<40} period={period:<10} last={last}{extra}"
            )

        lines.append("\n📊 **直近配信履歴**")
        if not posts:
            lines.append("  (まだ配信履歴がありません)")
        else:
            for p in posts:
                pt = (p.get("title") or "(削除済)")[:30]
                lines.append(
                    f"  {p['posted_at']} {p['trigger']:11} case_id={p['case_id']:>2} | {pt}"
                )

        msg = "\n".join(lines)
        if len(msg) > 1990:
            msg = msg[:1980] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(
        name="hjm-case-post-now",
        description="今すぐ 1 事例を配信(case_id 省略時は未配信から自動選定)",
    )
    @app_commands.describe(
        case_id="配信したい case_id(省略時は未配信から自動選定)",
    )
    async def hjm_case_post_now(
        interaction: discord.Interaction, case_id: int | None = None
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        ok = await dispatcher.generate_and_dispatch(
            interaction.client, trigger="manual", case_id=case_id
        )
        if ok:
            await interaction.followup.send(
                "✅ 事例配信を #hajime-cases に投下しました。", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠ 配信に失敗しました。詳細は #hajime-system-logs を確認してください。",
                ephemeral=True,
            )

    @bot.tree.command(
        name="hjm-case-show",
        description="指定した case_id の詳細(構造化済みデータ + 原文)を表示",
    )
    @app_commands.describe(case_id="表示したい case_id")
    async def hjm_case_show(
        interaction: discord.Interaction, case_id: int
    ) -> None:
        case = await asyncio.to_thread(repo.get_case, case_id)
        if case is None:
            await interaction.response.send_message(
                f"❌ case_id={case_id} が見つかりません", ephemeral=True
            )
            return
        lines = [
            f"💼 **事例 #{case['id']}** [status={case['status']}]",
            f"**タイトル**: {case.get('title', '')}",
        ]
        for label, key in (
            ("課題", "challenge"),
            ("実装", "implementation"),
            ("成果", "outcome"),
            ("数字", "impact_numbers"),
            ("出典", "source_url"),
            ("期間", "period"),
        ):
            v = (case.get(key) or "").strip()
            if v:
                lines.append(f"**{label}**: {v}")
        lines.append(f"\n*登録: {case.get('created_at')} · model={case.get('extraction_model')}*")
        lines.append(
            f"\n--- 原文 ---\n```{(case.get('raw_text') or '')[:1400]}```"
        )
        msg = "\n".join(lines)
        if len(msg) > 1990:
            msg = msg[:1980] + "\n…(truncated)"
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(
        name="hjm-case-sync",
        description="HajimeCases リポを今すぐ git pull → DB 反映",
    )
    async def hjm_case_sync(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            result = await asyncio.to_thread(git_sync.sync_from_git)
        except git_sync.GitSyncError as e:
            await interaction.followup.send(
                f"❌ git sync 失敗\n```{e}```", ephemeral=True
            )
            return
        lines = [
            f"✅ git sync 完了 (head=`{result.head_sha[:10]}`)",
            f"- ファイル: **{result.files_seen}** 件",
            f"- 反映: **{result.upserted}** 件",
            f"- 変更なし: {result.skipped_unchanged} 件",
            f"- スキップ(parse 失敗 or case_id 欠落): {result.skipped_invalid} 件",
        ]
        if result.errors:
            lines.append(f"\n⚠ エラー {len(result.errors)} 件:")
            for e in result.errors[:5]:
                lines.append(f"  - {e}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    log.info(
        "registered /hjm-case-list, /hjm-case-post-now, /hjm-case-show, /hjm-case-sync commands"
    )
