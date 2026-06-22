"""cases / case_posts テーブルの CRUD。"""

from __future__ import annotations

import json
import logging
from typing import Any

from ... import db as _db

log = logging.getLogger("hajime-ai-bot.cases.repo")

_ALLOWED_STATUSES = {"active", "paused", "gone"}
_ALLOWED_TRIGGERS = {"weekly_cron", "manual"}


# --- cases ---------------------------------------------------------------


def insert_case(
    *,
    title: str,
    raw_text: str,
    challenge: str = "",
    implementation: str = "",
    outcome: str = "",
    impact_numbers: str = "",
    source_url: str = "",
    period: str = "",
    discord_message_id: str | None = None,
    discord_channel_id: str | None = None,
    discord_author_id: str | None = None,
    extraction_model: str | None = None,
) -> int:
    if not title.strip():
        raise ValueError("title が空です")
    if not raw_text.strip():
        raise ValueError("raw_text が空です")
    with _db.get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO cases (
                title, raw_text, challenge, implementation, outcome,
                impact_numbers, source_url, period,
                discord_message_id, discord_channel_id, discord_author_id,
                extraction_model
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(), raw_text, challenge, implementation, outcome,
                impact_numbers, source_url, period,
                discord_message_id, discord_channel_id, discord_author_id,
                extraction_model,
            ),
        )
        return int(cur.lastrowid)


def get_case(case_id: int) -> dict | None:
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE id = ?", (int(case_id),)
        ).fetchone()
        return dict(row) if row else None


def list_active() -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, period, status, created_at, source_url, impact_numbers
            FROM cases
            WHERE status = 'active'
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(case_id: int, new_status: str) -> int:
    if new_status not in _ALLOWED_STATUSES:
        raise ValueError(f"unknown status {new_status!r}")
    with _db.get_connection() as conn:
        cur = conn.execute(
            "UPDATE cases SET status = ? WHERE id = ?",
            (new_status, int(case_id)),
        )
        return int(cur.rowcount)


def already_imported(discord_message_id: str) -> bool:
    """同じ Discord メッセージから二重 import を防ぐ判定。"""
    if not discord_message_id:
        return False
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM cases WHERE discord_message_id = ? LIMIT 1",
            (str(discord_message_id),),
        ).fetchone()
        return row is not None


# --- case_posts ----------------------------------------------------------


def insert_case_post(
    *,
    case_id: int,
    trigger: str,
    generated_patterns: list[dict[str, Any]],
    discord_message_id: str | None = None,
    model: str | None = None,
) -> int:
    if trigger not in _ALLOWED_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    with _db.get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO case_posts
                (case_id, trigger, generated_patterns, discord_message_id, model)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(case_id),
                trigger,
                json.dumps(generated_patterns, ensure_ascii=False),
                discord_message_id,
                model,
            ),
        )
        return int(cur.lastrowid)


def last_posted_at_by_case() -> dict[int, str]:
    """case_id -> 最終 posted_at のマップ。未配信 case は含まれない。"""
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT case_id, MAX(posted_at) AS last_at
            FROM case_posts
            GROUP BY case_id
            """
        ).fetchall()
        return {int(r["case_id"]): str(r["last_at"]) for r in rows}


def list_recent_posts(limit: int = 10) -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT cp.id, cp.case_id, cp.posted_at, cp.trigger, cp.model,
                   c.title
            FROM case_posts cp
            LEFT JOIN cases c ON c.id = cp.case_id
            ORDER BY cp.posted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def pick_next_unposted_case() -> dict | None:
    """配信優先順位:未配信 case > 最後に配信したのが最も古い case > id 昇順。

    active 状態の case のみ対象。
    """
    actives = list_active()
    if not actives:
        return None
    last_posted = last_posted_at_by_case()
    actives.sort(
        key=lambda c: (last_posted.get(int(c["id"]), ""), int(c["id"]))
    )
    return actives[0]
