"""自由文の事例投稿を Claude で構造化する。

#hajime-case-input への投稿を on_message が拾って呼び出す。
extractor は Discord 通信を持たない(テスト容易性)。
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

log = logging.getLogger("hajime-ai-bot.cases.extractor")

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1500

_PERSONA_PATH = Path(__file__).resolve().parents[3] / "prompts" / "persona.yaml"


@dataclass
class ExtractedCase:
    title: str
    challenge: str
    implementation: str
    outcome: str
    impact_numbers: str
    source_url: str
    period: str
    model: str


class ExtractorError(Exception):
    pass


def _load_persona() -> dict[str, Any]:
    if not _PERSONA_PATH.exists():
        raise ExtractorError(f"persona.yaml が見つかりません: {_PERSONA_PATH}")
    data = yaml.safe_load(_PERSONA_PATH.read_text(encoding="utf-8")) or {}
    if "cases" not in data or "system_prompt" not in data:
        raise ExtractorError(
            "persona.yaml に cases / system_prompt セクションがありません"
        )
    cases = data["cases"]
    if "extractor" not in cases:
        raise ExtractorError("persona.yaml の cases に extractor セクションがありません")
    return data


def extract_case(
    raw_text: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> ExtractedCase:
    """自由文 → 構造化された ExtractedCase。

    Raises
    ------
    ExtractorError
        API 鍵欠落 / Claude API 失敗 / JSON パース失敗 / title 欠落。
    """
    raw_text = (raw_text or "").strip()
    if len(raw_text) < 10:
        raise ExtractorError("事例本文が短すぎます(10 文字以上で投稿してください)")

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractorError("ANTHROPIC_API_KEY が未設定です")

    persona = _load_persona()
    system_base = persona["system_prompt"]
    cfg = persona["cases"]["extractor"]
    system_prompt = (system_base.rstrip() + "\n\n" + cfg["system_prompt_addon"]).strip()
    user_prompt = cfg["user_prompt_tmpl"].format(raw_text=raw_text)

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise ExtractorError(f"Claude API 呼び出し失敗: {e}") from e

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    raw = "\n".join(text_blocks)
    parsed = _extract_json(raw)
    if not parsed:
        raise ExtractorError(f"JSON パース失敗。raw len={len(raw)}")

    title = str(parsed.get("title", "")).strip()
    if not title:
        raise ExtractorError("title が抽出できませんでした(事例が明確でない可能性)")

    return ExtractedCase(
        title=title,
        challenge=str(parsed.get("challenge", "")).strip(),
        implementation=str(parsed.get("implementation", "")).strip(),
        outcome=str(parsed.get("outcome", "")).strip(),
        impact_numbers=str(parsed.get("impact_numbers", "")).strip(),
        source_url=str(parsed.get("source_url", "")).strip(),
        period=str(parsed.get("period", "")).strip(),
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
