"""今日配信する basics 用語を 1 つ選ぶ。

選定方針:
- persona.yaml の basics_catalog から、basics_history で「最後に配信したのが
  最も古い(or 未配信)」用語を選ぶ
- 未配信が複数あれば Tier 番号が小さい順、同 Tier なら id 順
- 全て配信済みなら最終配信が最古のもの(運用半年想定で 34 語が一巡)
- term_id 明示指定もできる(/hjm-basics term_id=5 等)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from . import repo

log = logging.getLogger("hajime-ai-bot.basics.selector")

_PERSONA_PATH = Path(__file__).resolve().parents[3] / "prompts" / "persona.yaml"


class SelectorError(Exception):
    pass


def _load_catalog() -> list[dict[str, Any]]:
    if not _PERSONA_PATH.exists():
        raise SelectorError(f"persona.yaml が見つかりません: {_PERSONA_PATH}")
    data = yaml.safe_load(_PERSONA_PATH.read_text(encoding="utf-8")) or {}
    catalog = data.get("basics_catalog")
    if not isinstance(catalog, list) or not catalog:
        raise SelectorError("persona.yaml に basics_catalog が無い / 空です")
    return [t for t in catalog if isinstance(t, dict) and "id" in t and "term" in t]


def get_term_by_id(term_id: int) -> dict[str, Any]:
    """ID 明示指定で取得。見つからなければ SelectorError。"""
    for t in _load_catalog():
        if int(t["id"]) == int(term_id):
            return t
    raise SelectorError(f"basics_catalog に id={term_id} の用語がありません")


def pick_next_term() -> dict[str, Any]:
    """次に配信する用語を返す。

    最後に配信したのが最も古い(or 未配信)用語を選ぶ。
    タイブレーク: Tier 番号小さい順 → id 順。
    """
    catalog = _load_catalog()
    last_posted = repo.last_posted_at_by_term()

    def sort_key(t: dict[str, Any]) -> tuple:
        tid = int(t["id"])
        last_at = last_posted.get(tid, "")  # 空文字列は最古扱い(未配信が最優先)
        tier = int(t.get("tier", 99))
        return (last_at, tier, tid)

    picked = sorted(catalog, key=sort_key)[0]
    log.info(
        "basics selector: picked id=%s term=%s tier=%s last_posted=%s",
        picked.get("id"),
        picked.get("term"),
        picked.get("tier"),
        last_posted.get(int(picked["id"]), "(未配信)"),
    )
    return picked
