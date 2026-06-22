"""basics_history CRUD。

どの term_id をいつ配信したかを記録。selector が「同じ単語を連続で配信しない」
判定材料に使う。
"""

from __future__ import annotations

import logging

from ... import db as _db

log = logging.getLogger("hajime-ai-bot.basics.repo")


def insert_history(
    *,
    term_id: int,
    term: str,
    generated_text: str | None = None,
    discord_message_id: str | None = None,
) -> int:
    with _db.get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO basics_history
                (term_id, term, generated_text, discord_message_id)
            VALUES (?, ?, ?, ?)
            """,
            (int(term_id), term, generated_text, discord_message_id),
        )
        return int(cur.lastrowid)


def last_posted_at_by_term() -> dict[int, str]:
    """term_id -> 最終 posted_at (ISO) のマップ。未配信 term は含まれない。"""
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT term_id, MAX(posted_at) AS last_at
            FROM basics_history
            GROUP BY term_id
            """
        ).fetchall()
        return {int(r["term_id"]): str(r["last_at"]) for r in rows}


def list_recent(limit: int = 10) -> list[dict]:
    with _db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, term_id, term, posted_at, generated_text, discord_message_id
            FROM basics_history
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count() -> int:
    with _db.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM basics_history").fetchone()
        return int(row["n"])
