-- 002_cases.sql
-- Phase 4-A: 自社内製事例の発信
-- 古谷さんが #hajime-case-input に自由文で投稿 → Claude が構造化 → DB 保存
-- 週 1 cron が未配信事例から 1 件 pickup → 3 パターン生成 → #hajime-cases 配信

-- ===========================================================================
-- cases: 事例マスタ(古谷さんの内製事例)
-- ===========================================================================
CREATE TABLE cases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT    NOT NULL,            -- Claude が抽出した短いタイトル
    raw_text            TEXT    NOT NULL,            -- 投稿原文(参照用、Claude 再実行用)
    challenge           TEXT,                         -- 課題(構造化済)
    implementation      TEXT,                         -- 実装内容
    outcome             TEXT,                         -- 成果
    impact_numbers      TEXT,                         -- 数字インパクト(例: "30分→5分")
    source_url          TEXT,                         -- 業界誌記事 / リポ URL
    period              TEXT,                         -- 実装期間 (例: "2025-08")
    status              TEXT    NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'paused', 'gone')),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    -- 登録元の Discord メッセージ追跡(再抽出時の参照、誰が登録したかの記録)
    discord_message_id  TEXT,
    discord_channel_id  TEXT,
    discord_author_id   TEXT,
    extraction_model    TEXT
);

CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_created ON cases(created_at);


-- ===========================================================================
-- case_posts: 1 事例の配信履歴
-- ===========================================================================
-- 同じ case が複数回配信される可能性もあるので 1:N。selector が「最後に配信
-- したのが最も古い case」or「未配信 case」を優先する判定材料。
CREATE TABLE case_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             INTEGER NOT NULL,
    posted_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    trigger             TEXT    NOT NULL
                        CHECK(trigger IN ('weekly_cron', 'manual')),
    generated_patterns  TEXT,                         -- JSON: [{pattern, text, chars}, ...]
    discord_message_id  TEXT,                         -- 配信先 #hajime-cases メッセージ ID
    model               TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX idx_case_posts_case ON case_posts(case_id);
CREATE INDEX idx_case_posts_posted ON case_posts(posted_at);
