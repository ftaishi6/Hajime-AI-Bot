"""Hajime-AI-Bot エントリポイント。

Phase 2: `/hjm-ping` / `/hjm-health` の常駐確認骨組み。
Phase 3-A: `/hjm-curate` + `/hjm-watch` グループ → #hajime-curation
Phase 3-B: `/hjm-basics` + `/hjm-basics-history` → #hajime-basics
スケジューラは 07:00 JST に curation、12:00 JST に basics を回す。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import discord
import yaml
from discord import app_commands
from dotenv import load_dotenv

from . import __version__
from . import db as _db
from . import scheduler as _scheduler
from .features.basics import commands as _basics_commands
from .features.curation import commands as _curation_commands
from .features.curation import repo as _curation_repo

# --- 環境変数読み込み ------------------------------------------------------
ENV_PATH = Path("/opt/hajime-ai-bot/.env")
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)


def _require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"環境変数 {name} が未設定です。/opt/hajime-ai-bot/.env を確認してください。"
        )
    return v


TOKEN = _require("DISCORD_BOT_TOKEN")
GUILD_ID = int(_require("DISCORD_GUILD_ID"))
SYSTEM_LOGS_CHANNEL_ID = int(_require("DISCORD_CHANNEL_SYSTEM_LOGS"))

# --- ロギング設定 ----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("hajime-ai-bot")

# --- Bot 本体 --------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class HajimeBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.started_at: float = time.time()

    async def setup_hook(self) -> None:
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild=%s (count=%d)", GUILD_ID, len(synced))
        # config.yaml の watch_accounts を起動時に DB と sync
        try:
            entries = _load_config_watch_accounts()
            if entries:
                added, kept = await asyncio.to_thread(
                    _curation_repo.sync_from_config, entries
                )
                log.info(
                    "startup sync_from_config: added=%d kept=%d (total=%d)",
                    added, kept, added + kept,
                )
        except Exception:
            log.exception("startup sync_from_config failed (non-fatal)")
        # APScheduler を起動(curation 07:00 / basics 12:00 JST)
        _scheduler.start_scheduler(self)


bot = HajimeBot()


@bot.tree.command(name="hjm-ping", description="Hajime-AI-Bot 疎通確認(レイテンシだけ返す)")
async def cmd_ping(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"pong (Hajime-AI-Bot, latency: {latency_ms}ms)")


@bot.tree.command(name="hjm-health", description="Hajime-AI-Bot のヘルスチェック")
async def cmd_health(interaction: discord.Interaction) -> None:
    uptime_sec = int(time.time() - bot.started_at)
    uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"
    now_jst = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    msg = (
        "✅ **OK** (Hajime-AI-Bot)\n"
        f"- guild: `{GUILD_ID}`\n"
        f"- bot user: `{bot.user}` (id=`{bot.user.id}`)\n"
        f"- latency: `{round(bot.latency * 1000)}ms`\n"
        f"- uptime: `{uptime_str}`\n"
        f"- python: `{sys.version.split()[0]}`\n"
        f"- discord.py: `{discord.__version__}`\n"
        f"- version: `{__version__}`\n"
        f"- now: `{now_jst}`"
    )
    await interaction.response.send_message(msg)


# 機能パッケージのコマンド登録(setup_hook での tree.sync 前に呼ぶ必要がある)
_curation_commands.setup(bot)
_basics_commands.setup(bot)


def _load_config_watch_accounts() -> list[dict]:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    if not config_path.exists():
        return []
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = data.get("watch_accounts", [])
    return entries if isinstance(entries, list) else []


async def _post_system_log(content: str) -> None:
    """`#hajime-system-logs` に投稿する。"""
    channel = bot.get_channel(SYSTEM_LOGS_CHANNEL_ID)
    if channel is None:
        log.warning(
            "system-logs channel not in cache; cannot post: %s", content[:80]
        )
        return
    if len(content) > 1900:
        content = content[:1900] + "\n…(truncated)"
    try:
        await channel.send(content)
    except Exception:
        log.exception("Failed to post to #hajime-system-logs")


@bot.event
async def on_ready() -> None:
    assert bot.user is not None
    log.info("Logged in as %s (id=%s)", bot.user, bot.user.id)
    now_jst = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    await _post_system_log(
        f"🟢 **Hajime-AI-Bot started** — `{bot.user}` v{__version__}\n"
        f"- python `{sys.version.split()[0]}`, discord.py `{discord.__version__}`\n"
        f"- at `{now_jst}`"
    )


@bot.event
async def on_error(event_method: str, *args, **kwargs) -> None:  # noqa: ANN002 ANN003
    exc_type, exc_value, exc_tb = sys.exc_info()
    log.exception("Unhandled exception in event %s", event_method)
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    await _post_system_log(
        f"⚠️ **Unhandled error** in event `{event_method}`\n"
        f"```py\n{tb_text}\n```"
    )


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    cmd_name = interaction.command.name if interaction.command else "unknown"
    user = interaction.user
    log.exception("Slash command /%s failed for %s: %s", cmd_name, user, error)
    tb_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    await _post_system_log(
        f"⚠️ **/`{cmd_name}` failed** for `{user}` (id=`{user.id}`)\n"
        f"```py\n{tb_text}\n```"
    )
    msg = f"⚠ `/{cmd_name}` でエラーが発生しました。詳細は #hajime-system-logs を確認してください。"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        log.exception("Failed to respond to interaction after error")


def main() -> None:
    logging.getLogger("discord").setLevel(logging.WARNING)
    log.info("Starting hajime-ai-bot")
    _db.init_db()
    log.info("DB initialized at %s", _db.DB_PATH)
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
