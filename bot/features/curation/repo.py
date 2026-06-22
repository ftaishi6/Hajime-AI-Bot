"""watch_accounts / curation_history テーブルの CRUD。

Xapp の watch.repo と同パターン(handle を unique key、source は config/manual)。
"""

from __future__ import annotations

import logging
from typing import Iterable

from ... import db as _db

log = logging.getLogger("hajime-ai-bot.curation.repo")

_ALLOWED_STATUSES = {"active", "paused", "gone"}
_ALLOWED_SOURCES = {"config", "manual"}
_ALLOWED_TRIGGERS = {"daily_cron", "manual"}


def _norm_handle(handle: str) -> str:
    return handle.lstrip("@").strip()


def upsert_account(
    handle: str,
    *,
    source: str = "manual",
    notes: str | None = None,
    display_name: str | None = None,
    user_id: str | None = None,
) -> tuple[int, bool]:
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"unknown source {source!r}")
    handle = _norm_handle(handle)
    if not handle:
        raise ValueError("handle が空です")

    with _db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM watch_accounts WHERE handle = ?", (handle,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE watch_accounts
                SET notes = COALESCE(?, notes),
                    display_name = COALESCE(?, display_name),
                    user_id = COALESCE(?, user_id)
                WHERE id = ?
                """,
                (notes, display_name, user_id, existing["id"]),
            )
            return int(existing["id"]), False
        cur = conn.execute(
            """
            INSERT INTO watch_accounts (handle, source, notes, display_name, user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (handle, source, notes, display_name, user_id),
        )
        return int(cur.lastrowid), True


def update_user_id(handle: str, user_id: str, display_name: str | None = None) -> None:
    with _db.get_connection() as conn:
        conn.execute(
            """
            UPDATE watch_accounts
            SET user_id = ?, display_name = COALESCE(?, display_name)
            WHERE handle = ?
            """,
            (user_id, display_name, _norm_handle(handle)),
        )


def set_last_fetched(handle: str) -> None:
    with _db.get_connection() as conn:
        conn.execute(
            "UPDATE watch_accounts SET last_fetched_at = datetime('now') WHERE handle = ?",
            (_norm_handle(handle),),
        )


def list_active() -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, handle, user_id, display_name, source, notes,
                   added_at, last_fetched_at, status
            FROM watch_accounts
            WHERE status = 'active'
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def list_all() -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, handle, user_id, display_name, source, notes,
                   added_at, last_fetched_at, status
            FROM watch_accounts
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(handle: str, new_status: str) -> int:
    if new_status not in _ALLOWED_STATUSES:
        raise ValueError(f"unknown status {new_status!r}")
    with _db.get_connection() as conn:
        cur = conn.execute(
            "UPDATE watch_accounts SET status = ? WHERE handle = ?",
            (new_status, _norm_handle(handle)),
        )
        return int(cur.rowcount)


def sync_from_config(config_entries: Iterable[dict]) -> tuple[int, int]:
    added = 0
    kept = 0
    for entry in config_entries:
        if not isinstance(entry, dict):
            continue
        handle = str(entry.get("handle", "")).strip()
        if not handle:
            continue
        notes = entry.get("notes")
        _, is_new = upsert_account(handle, source="config", notes=notes)
        if is_new:
            added += 1
        else:
            kept += 1
    log.info("curation sync_from_config: added=%d kept=%d", added, kept)
    return (added, kept)


# --- curation_history -----------------------------------------------------


def insert_curation_run(
    *,
    trigger: str,
    accounts_scanned: int,
    tweets_fetched: int,
    highlights_count: int,
    model: str | None = None,
    notes: str | None = None,
) -> int:
    if trigger not in _ALLOWED_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    with _db.get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO curation_history
                (trigger, accounts_scanned, tweets_fetched, highlights_count, model, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (trigger, accounts_scanned, tweets_fetched, highlights_count, model, notes),
        )
        return int(cur.lastrowid)


def list_recent_runs(limit: int = 5) -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, run_at, trigger, accounts_scanned, tweets_fetched,
                   highlights_count, model, notes
            FROM curation_history
            ORDER BY run_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
