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
from apscheduler.triggers.interval import IntervalTrigger

from .features.basics.dispatcher import generate_and_dispatch as basics_generate_and_dispatch
from .features.cases.dispatcher import generate_and_dispatch as cases_generate_and_dispatch
from .features.cases.git_sync import sync_from_git as cases_git_sync
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

    # 自社内製事例: 毎週火曜 09:00 JST に未配信事例から 1 件 → #hajime-cases へ。
    # 手動 /hjm-case-post-now でも同じ dispatcher を呼ぶ。
    sched.add_job(
        cases_generate_and_dispatch,
        CronTrigger(day_of_week="tue", hour=9, minute=0, timezone="Asia/Tokyo"),
        args=[bot],
        kwargs={"trigger": "weekly_cron"},
        id="cases.weekly",
        name="cases: weekly Tue 09:00 JST",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # HajimeCases リポ(Obsidian Vault)を 30 分間隔で git pull → DB 反映。
    # 古谷さんが Obsidian で書いて push → 30 分以内に Bot 側に反映される。
    # 手動 /hjm-case-sync でも同じ関数を呼ぶ。
    sched.add_job(
        cases_git_sync,
        IntervalTrigger(minutes=30),
        id="cases.git_sync",
        name="cases: git sync (every 30 min)",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    sched.start()

    # 起動直後に 1 回 git_sync を即実行(初回反映を 30 分待たせない)
    try:
        from datetime import datetime, timedelta  # noqa: PLC0415
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        sched.modify_job(
            "cases.git_sync",
            next_run_time=datetime.now(ZoneInfo("Asia/Tokyo")) + timedelta(seconds=15),
        )
        log.info("cases.git_sync armed for immediate first run (+15s)")
    except Exception:
        log.exception("failed to arm immediate git_sync")
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
