"""HajimeCases リポ(古谷さんの Obsidian Vault)から git pull + parse + upsert。

呼び出し側(scheduler / 手動 /hjm-case-sync コマンド)は ``sync_from_git()``
を呼ぶだけ。Discord 通信を持たない(テスト容易性)。

Markdown フォーマット:
- frontmatter (YAML) に case_id / title / period / source_url / impact_numbers /
  status / tags
- 本文に ``## 課題`` ``## 実装`` ``## 成果`` ``## 補足・学び`` の section
- challenge / implementation / outcome は section 本文をそのまま使う
- 補足・学び section は Bot 側では使わない

設定:
- 環境変数 HAJIME_CASES_VAULT_PATH  (default: /opt/hajime-ai-bot/cases-vault)
- 環境変数 HAJIME_CASES_VAULT_GLOB  (default: Cases/*.md)
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from ... import db as _db

log = logging.getLogger("hajime-ai-bot.cases.git_sync")

DEFAULT_VAULT_PATH = Path(os.environ.get("HAJIME_CASES_VAULT_PATH", "/opt/hajime-ai-bot/cases-vault"))
DEFAULT_GLOB = os.environ.get("HAJIME_CASES_VAULT_GLOB", "Cases/*.md")

# Bot が読む section 見出し ⇒ DB カラム
_SECTION_MAP = {
    "課題": "challenge",
    "実装": "implementation",
    "成果": "outcome",
}
_VALID_STATUSES = {"active", "paused", "gone"}


class GitSyncError(Exception):
    pass


@dataclass
class SyncResult:
    head_sha: str
    files_seen: int
    upserted: int           # 新規 or 内容更新で DB へ反映した数
    skipped_unchanged: int  # git_sha 同じで skip
    skipped_invalid: int    # parse 失敗 / case_id 欠落
    deleted: int            # status=gone 反映
    errors: list[str]


# --- public API ---------------------------------------------------------


def sync_from_git(
    *,
    vault_path: Path = DEFAULT_VAULT_PATH,
    glob_pat: str = DEFAULT_GLOB,
    do_pull: bool = True,
) -> SyncResult:
    """git pull → Markdown を parse → DB upsert。

    Raises
    ------
    GitSyncError
        vault が存在しない / git コマンド失敗。
    """
    if not vault_path.is_dir():
        raise GitSyncError(
            f"vault が見つかりません: {vault_path}"
            " (clone 済みか HAJIME_CASES_VAULT_PATH を確認)"
        )
    if not (vault_path / ".git").is_dir():
        raise GitSyncError(f"git リポではない: {vault_path}")

    if do_pull:
        _git_pull(vault_path)

    head_sha = _git_head_sha(vault_path)
    log.info("git_sync: vault=%s head=%s", vault_path, head_sha[:10])

    files_seen = 0
    upserted = 0
    skipped_unchanged = 0
    skipped_invalid = 0
    errors: list[str] = []

    md_paths = sorted(vault_path.glob(glob_pat))
    for md in md_paths:
        files_seen += 1
        rel_slug = str(md.relative_to(vault_path))
        try:
            parsed = _parse_case_md(md.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("git_sync: parse failed %s: %s", rel_slug, e)
            errors.append(f"{rel_slug}: parse failed: {e}")
            skipped_invalid += 1
            continue

        if parsed is None:
            log.warning("git_sync: %s に case_id が無いので skip", rel_slug)
            skipped_invalid += 1
            continue

        case_id = parsed["case_id"]
        file_sha = _git_file_last_sha(vault_path, rel_slug) or head_sha

        action = _upsert_case(
            case_id=case_id,
            slug=rel_slug,
            git_sha=file_sha,
            parsed=parsed,
        )
        if action == "upserted":
            upserted += 1
        elif action == "unchanged":
            skipped_unchanged += 1

    # status=gone 反映(該当 case が存在しなくなった場合の Soft delete は別途、
    # 今は明示的に status: gone を frontmatter に書いた行のみ反映済み)
    deleted = _count_gone()

    result = SyncResult(
        head_sha=head_sha,
        files_seen=files_seen,
        upserted=upserted,
        skipped_unchanged=skipped_unchanged,
        skipped_invalid=skipped_invalid,
        deleted=deleted,
        errors=errors,
    )
    log.info(
        "git_sync done: seen=%d upserted=%d unchanged=%d invalid=%d gone=%d errors=%d",
        files_seen, upserted, skipped_unchanged, skipped_invalid, deleted, len(errors),
    )
    return result


# --- git helpers --------------------------------------------------------


def _git_pull(vault_path: Path) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(vault_path), "fetch", "--quiet", "origin", "main"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(vault_path), "reset", "--hard", "--quiet", "origin/main"],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except subprocess.CalledProcessError as e:
        raise GitSyncError(
            f"git fetch/reset 失敗: {e.stderr or e.stdout}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise GitSyncError("git fetch/reset がタイムアウトしました") from e


def _git_head_sha(vault_path: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(vault_path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitSyncError(f"git rev-parse HEAD 失敗: {e.stderr}") from e


def _git_file_last_sha(vault_path: Path, rel_path: str) -> str | None:
    """ファイル単位で最終 commit SHA を取る(差分判定用)。"""
    try:
        res = subprocess.run(
            ["git", "-C", str(vault_path), "log", "-1", "--format=%H", "--", rel_path],
            check=True, capture_output=True, text=True, timeout=10,
        )
        sha = res.stdout.strip()
        return sha or None
    except subprocess.CalledProcessError:
        return None


# --- markdown parsing ---------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s+|\Z)", re.S | re.M)


def _parse_case_md(text: str) -> dict | None:
    """Markdown 全文を {case_id, title, ...} dict に。case_id 欠落なら None。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise GitSyncError("frontmatter (--- ... ---) が見つかりません")
    fm_yaml = m.group(1)
    body = m.group(2)

    try:
        fm = yaml.safe_load(fm_yaml) or {}
    except yaml.YAMLError as e:
        raise GitSyncError(f"frontmatter YAML パース失敗: {e}") from e
    if not isinstance(fm, dict):
        raise GitSyncError("frontmatter が dict 形式でありません")

    case_id = fm.get("case_id")
    if not isinstance(case_id, int):
        # case_id が未設定 or 非数値 → 未確定とみなして skip
        return None

    status = str(fm.get("status", "active")).strip().lower()
    if status not in _VALID_STATUSES:
        log.warning("invalid status=%r in case_id=%s, fallback active", status, case_id)
        status = "active"

    sections = _extract_sections(body)
    challenge = sections.get("challenge", "").strip()
    implementation = sections.get("implementation", "").strip()
    outcome = sections.get("outcome", "").strip()

    return {
        "case_id": int(case_id),
        "title": str(fm.get("title", "")).strip(),
        "period": str(fm.get("period", "") or "").strip(),
        "source_url": str(fm.get("source_url", "") or "").strip(),
        "impact_numbers": str(fm.get("impact_numbers", "") or "").strip(),
        "status": status,
        "challenge": challenge,
        "implementation": implementation,
        "outcome": outcome,
        "raw_text": text,
    }


def _extract_sections(body: str) -> dict[str, str]:
    """## 課題 / 実装 / 成果 を {challenge, implementation, outcome} に抽出。"""
    out: dict[str, str] = {}
    for m in _SECTION_RE.finditer(body):
        heading = m.group(1).strip()
        content = m.group(2).strip()
        key = _SECTION_MAP.get(heading)
        if key:
            out[key] = content
    return out


# --- DB upsert ----------------------------------------------------------


def _upsert_case(
    *, case_id: int, slug: str, git_sha: str, parsed: dict
) -> str:
    """case_id を主キーに UPSERT。

    既存と git_sha が同じなら "unchanged"、変わったら "upserted"。
    Returns "upserted" / "unchanged"
    """
    with _db.get_connection() as conn:
        existing = conn.execute(
            "SELECT git_sha FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if existing and existing["git_sha"] == git_sha:
            return "unchanged"

        if existing is None:
            conn.execute(
                """
                INSERT INTO cases (
                    id, title, raw_text, challenge, implementation, outcome,
                    impact_numbers, source_url, period, status,
                    source, slug, git_sha, last_synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'obsidian_git', ?, ?, datetime('now'))
                """,
                (
                    case_id,
                    parsed["title"],
                    parsed["raw_text"],
                    parsed["challenge"],
                    parsed["implementation"],
                    parsed["outcome"],
                    parsed["impact_numbers"],
                    parsed["source_url"],
                    parsed["period"],
                    parsed["status"],
                    slug,
                    git_sha,
                ),
            )
            log.info("git_sync: insert case_id=%d slug=%s", case_id, slug)
        else:
            conn.execute(
                """
                UPDATE cases SET
                    title = ?, raw_text = ?, challenge = ?, implementation = ?,
                    outcome = ?, impact_numbers = ?, source_url = ?, period = ?,
                    status = ?, source = 'obsidian_git', slug = ?, git_sha = ?,
                    last_synced_at = datetime('now')
                WHERE id = ?
                """,
                (
                    parsed["title"],
                    parsed["raw_text"],
                    parsed["challenge"],
                    parsed["implementation"],
                    parsed["outcome"],
                    parsed["impact_numbers"],
                    parsed["source_url"],
                    parsed["period"],
                    parsed["status"],
                    slug,
                    git_sha,
                    case_id,
                ),
            )
            log.info("git_sync: update case_id=%d slug=%s", case_id, slug)
    return "upserted"


def _count_gone() -> int:
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM cases WHERE status = 'gone'"
        ).fetchone()
        return int(row["n"])
