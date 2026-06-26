-- 003_cases_obsidian_sync.sql
-- Phase 4-B: Obsidian Vault (HajimeCases リポ) からの git sync 対応。
--
-- 既存の cases テーブルに以下を足す:
--   source         : 事例の出所('discord' = #hajime-case-input 経由、'obsidian_git' = git sync 経由)
--   slug           : git リポ上の相対パス(例: "Cases/001-pwa-honnin-kakunin.md")
--   git_sha        : 最後に sync した git commit SHA(差分検出用)
--   last_synced_at : 最後に DB へ反映した時刻
--
-- 既存行は source='discord' を入れる(Phase 4-A 経由で入った想定)。
-- slug は obsidian_git 由来のときだけ NOT NULL。

ALTER TABLE cases ADD COLUMN source TEXT NOT NULL DEFAULT 'discord'
    CHECK(source IN ('discord', 'obsidian_git'));
ALTER TABLE cases ADD COLUMN slug TEXT;
ALTER TABLE cases ADD COLUMN git_sha TEXT;
ALTER TABLE cases ADD COLUMN last_synced_at TEXT;

CREATE INDEX idx_cases_source ON cases(source);
CREATE UNIQUE INDEX idx_cases_slug ON cases(slug) WHERE slug IS NOT NULL;
