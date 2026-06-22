"""basics の本文を Claude で生成する。

呼び出し側 (dispatcher) は term dict を渡し、generated_text と meta を受け取る。
generator は Discord 通信を持たない(テスト容易性)。
"""

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

log = logging.getLogger("hajime-ai-bot.basics.generator")

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 800

_PERSONA_PATH = Path(__file__).resolve().parents[3] / "prompts" / "persona.yaml"


@dataclass
class BasicsResult:
    term_id: int
    term: str
    en: str
    tier: int
    text: str         # 生成された本文(目標 140 字以内)
    over_limit: bool  # 140 字超過していたら True(配信側で警告マーカー)


class GeneratorError(Exception):
    pass


def _load_persona() -> dict[str, Any]:
    if not _PERSONA_PATH.exists():
        raise GeneratorError(f"persona.yaml が見つかりません: {_PERSONA_PATH}")
    data = yaml.safe_load(_PERSONA_PATH.read_text(encoding="utf-8")) or {}
    if "basics" not in data or "system_prompt" not in data:
        raise GeneratorError(
            "persona.yaml に basics / system_prompt セクションがありません"
        )
    return data


def generate_basics(
    term: dict[str, Any],
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> BasicsResult:
    """1 用語分の本文を Claude で生成する。

    Raises
    ------
    GeneratorError
        API 鍵欠落 / Claude API 失敗 / JSON パース失敗。
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise GeneratorError("ANTHROPIC_API_KEY が未設定です")

    persona = _load_persona()
    system_base = persona["system_prompt"]
    basics_cfg = persona["basics"]
    system_addon = basics_cfg["system_prompt_addon"]
    user_tmpl = basics_cfg["user_prompt_tmpl"]

    system_prompt = (system_base.rstrip() + "\n\n" + system_addon).strip()
    user_prompt = user_tmpl.format(
        term=term.get("term", ""),
        en=term.get("en", ""),
        tier=term.get("tier", ""),
        description=term.get("description", ""),
        angle=term.get("angle", ""),
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
    raw_text = "\n".join(text_blocks)
    parsed = _extract_json(raw_text)
    if not parsed or not isinstance(parsed.get("text"), str):
        raise GeneratorError(f"JSON パース失敗 / text 欠落。raw len={len(raw_text)}")

    body = parsed["text"].strip()
    if not body:
        raise GeneratorError("生成された text が空です")

    over = len(body) > 140
    if over:
        log.warning(
            "basics: generated text exceeds 140 chars (len=%d) for term=%s",
            len(body), term.get("term"),
        )

    return BasicsResult(
        term_id=int(term["id"]),
        term=str(term["term"]),
        en=str(term.get("en", "")),
        tier=int(term.get("tier", 0)),
        text=body,
        over_limit=over,
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
