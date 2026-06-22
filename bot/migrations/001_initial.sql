-- 001_initial.sql
-- Hajime-AI-Bot 初期スキーマ。
-- 起動時に最小限の table だけ用意。各機能は Phase 3 以降で migration 追加。

-- ===========================================================================
-- watch_accounts: 発信者ウォッチ対象
-- ===========================================================================
-- Xapp の同名テーブルと同設計。config.yaml の watch_accounts と起動時 sync。
CREATE TABLE watch_accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    handle              TEXT    NOT NULL UNIQUE,
    user_id             TEXT,
    display_name        TEXT,
    source              TEXT    NOT NULL DEFAULT 'manual'
                        CHECK(source IN ('config', 'manual')),
    notes               TEXT,
    added_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    last_fetched_at     TEXT,
    status              TEXT    NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'paused', 'gone'))
);

CREATE INDEX idx_watch_accounts_status ON watch_accounts(status);


-- ===========================================================================
-- basics_history: 基礎用語解説の配信履歴
-- ===========================================================================
-- どの単語をいつ配信したかを記録。同じ単語の重複連続配信を避けるための判定材料。
CREATE TABLE basics_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id         INTEGER NOT NULL,            -- persona.yaml の basics_catalog.id
    term            TEXT    NOT NULL,            -- 用語名(参照用、catalog 変更時の保険)
    posted_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    generated_text  TEXT,                         -- Claude が生成した本文
    discord_message_id TEXT
);

CREATE INDEX idx_basics_history_term ON basics_history(term_id);
CREATE INDEX idx_basics_history_postedat ON basics_history(posted_at);


-- ===========================================================================
-- curation_history: キュレーション配信履歴(将来用、今は空テーブルで OK)
-- ===========================================================================
CREATE TABLE curation_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    trigger             TEXT    NOT NULL
                        CHECK(trigger IN ('daily_cron', 'manual')),
    accounts_scanned    INTEGER NOT NULL DEFAULT 0,
    tweets_fetched      INTEGER NOT NULL DEFAULT 0,
    highlights_count    INTEGER NOT NULL DEFAULT 0,
    notes               TEXT,
    model               TEXT
);

CREATE INDEX idx_curation_history_run ON curation_history(run_at);
