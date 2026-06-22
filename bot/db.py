"""SQLite 接続と起動時マイグレーション(Xapp の同名モジュールと同パターン)。

DB ファイルは VPS 上の ``/opt/hajime-ai-bot/hajime.db``。環境変数
``HAJIME_DB_PATH`` で上書き可(ローカルテスト用)。

マイグレーションは ``bot/migrations/*.sql`` をファイル名昇順に適用する。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger("hajime-ai-bot.db")

DB_PATH = Path(os.environ.get("HAJIME_DB_PATH", "/opt/hajime-ai-bot/hajime.db"))
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Connection を取り、例外なしなら commit、ありなら rollback して close。"""
    conn = sqlite3.connect(DB_PATH, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """DB ファイルを作って WAL 化、未適用マイグレーションを実行する。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()

    with get_connection() as conn:
        _ensure_migration_table(conn)
        _apply_pending_migrations(conn)


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _apply_pending_migrations(conn: sqlite3.Connection) -> None:
    if not MIGRATIONS_DIR.is_dir():
        log.warning("migrations dir not found: %s", MIGRATIONS_DIR)
        return

    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations")
    }
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    pending = [p for p in sql_files if p.stem not in applied]

    if not pending:
        log.debug("no pending migrations (applied=%d)", len(applied))
        return

    log.info("applying %d pending migration(s)", len(pending))
    for sql_path in pending:
        version = sql_path.stem
        sql_text = sql_path.read_text(encoding="utf-8")
        try:
            conn.executescript(sql_text)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
            log.info("applied migration: %s", version)
        except Exception:
            log.exception("failed migration: %s — rolling back and aborting", version)
            conn.rollback()
            raise
