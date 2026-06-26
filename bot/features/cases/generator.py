"""1 事例 → 3 パターン(story / numbers / introspection)の投稿案を Claude で生成。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from anthropic import Anthropic

log = logging.getLogger("hajime-ai-bot.cases.generator")

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 2500

VALID_PATTERNS = ("story", "numbers", "introspection")

_PERSONA_PATH = Path(__file__).resolve().parents[3] / "prompts" / "persona.yaml"


@dataclass
class CasePattern:
    pattern: str  # story / numbers / introspection
    text: str
    chars: int
    over_limit: bool


@dataclass
class GeneratedCasePost:
    case_id: int
    patterns: list[CasePattern]
    model: str


class GeneratorError(Exception):
    pass


def _load_persona() -> dict[str, Any]:
    if not _PERSONA_PATH.exists():
        raise GeneratorError(f"persona.yaml が見つかりません: {_PERSONA_PATH}")
    data = yaml.safe_load(_PERSONA_PATH.read_text(encoding="utf-8")) or {}
    if "cases" not in data or "system_prompt" not in data:
        raise GeneratorError(
            "persona.yaml に cases / system_prompt セクションがありません"
        )
    cases = data["cases"]
    if "generator" not in cases:
        raise GeneratorError("persona.yaml の cases に generator セクションがありません")
    return data


def generate_patterns(
    case: dict,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> GeneratedCasePost:
    """case dict から 3 パターンを生成。

    case は repo.get_case() の戻り値想定。
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise GeneratorError("ANTHROPIC_API_KEY が未設定です")

    persona = _load_persona()
    system_base = persona["system_prompt"]
    cfg = persona["cases"]["generator"]
    system_prompt = (system_base.rstrip() + "\n\n" + cfg["system_prompt_addon"]).strip()
    # raw_text(本文全文)を主素材として渡す。古谷さんの自由フォーマット
    # (## 01: / ## 02: / 【何が起きたか】等)をそのまま Claude が読む。
    raw_text = case.get("raw_text") or ""
    # 本文長すぎる場合は安全側で切る(Claude max_tokens を超えないように)
    if len(raw_text) > 24000:
        raw_text = raw_text[:24000] + "\n\n…(本文が長いためここで切り詰め)"
    user_prompt = cfg["user_prompt_tmpl"].format(
        title=case.get("title", ""),
        period=case.get("period", "") or "(明示なし)",
        impact_numbers=case.get("impact_numbers", "") or "(なし)",
        raw_text=raw_text or "(本文なし)",
    )

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise GeneratorError(f"Claude API 呼び出し失敗: {e}") from e

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    raw = "\n".join(text_blocks)
    parsed = _extract_json(raw)
    if not parsed or not isinstance(parsed.get("patterns"), list):
        raise GeneratorError(f"JSON パース失敗 / patterns 欠落。raw len={len(raw)}")

    out: list[CasePattern] = []
    seen_patterns: set[str] = set()
    for item in parsed["patterns"]:
        if not isinstance(item, dict):
            continue
        pat = str(item.get("pattern", "")).strip().lower()
        text = str(item.get("text", "")).strip()
        if pat not in VALID_PATTERNS:
            log.warning("cases generator: unknown pattern %r, skip", pat)
            continue
        if pat in seen_patterns:
            log.warning("cases generator: duplicate pattern %r, skip", pat)
            continue
        if not text:
            log.warning("cases generator: empty text for pattern %r, skip", pat)
            continue
        chars = len(text)
        over = chars > 140
        if over:
            log.warning(
                "cases generator: pattern=%s over 140 chars (len=%d)", pat, chars
            )
        out.append(CasePattern(pattern=pat, text=text, chars=chars, over_limit=over))
        seen_patterns.add(pat)

    if not out:
        raise GeneratorError("有効な patterns が 1 つも抽出できませんでした")

    return GeneratedCasePost(
        case_id=int(case["id"]),
        patterns=out,
        model=model,
    )


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or first >= last:
        return None
    try:
        return json.loads(text[first : last + 1])
    except json.JSONDecodeError:
        return None
