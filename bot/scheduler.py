"""APScheduler を Bot プロセス内で起動する。

責務:
- 起動時に AsyncIOScheduler を初期化
- curation: 毎日 07:00 JST → #hajime-curation
- basics:   毎日 12:00 JST → #hajime-basics

setup_hook 等の async コンテキストで初期化すること
(同期 context で start() するとループを掴めない)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .features.basics.dispatcher import generate_and_dispatch as basics_generate_and_dispatch
from .features.curation.dispatcher import run_and_dispatch as curation_run_and_dispatch

if TYPE_CHECKING:
    import discord

log = logging.getLogger("hajime-ai-bot.scheduler")

_scheduler: AsyncIOScheduler | None = None


def start_scheduler(bot: "discord.Client") -> AsyncIOScheduler:
    """AsyncIOScheduler を起動して定期 job を仕込む(idempotent)。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        log.warning("start_scheduler called twice; returning existing instance")
        return _scheduler

    sched = AsyncIOScheduler(timezone="Asia/Tokyo")

    # キュレーション: 毎日 07:00 JST に digest を #hajime-curation へ。
    # 手動 /hjm-curate でも同じ dispatcher を呼ぶ。
    sched.add_job(
        curation_run_and_dispatch,
        CronTrigger(hour=7, minute=0, timezone="Asia/Tokyo"),
        args=[bot],
        kwargs={"trigger": "daily_cron"},
        id="curation.daily",
        name="curation: daily 07:00 JST",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # 基礎用語解説: 毎日 12:00 JST に 1 単語 → #hajime-basics へ。
    # 手動 /hjm-basics でも同じ dispatcher を呼ぶ。
    sched.add_job(
        basics_generate_and_dispatch,
        CronTrigger(hour=12, minute=0, timezone="Asia/Tokyo"),
        args=[bot],
        kwargs={"trigger": "daily_cron"},
        id="basics.daily",
        name="basics: daily 12:00 JST",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    sched.start()
    log.info(
        "scheduler started with %d job(s): %s",
        len(sched.get_jobs()),
        [j.id for j in sched.get_jobs()],
    )
    _scheduler = sched
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler shut down")
        _scheduler = None
