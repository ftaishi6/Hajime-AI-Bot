"""watchlist の直近投稿を取得 → Claude で top 3 highlight を抽出する。

Hajime ペルソナ用に persona.yaml の `curation` セクションを読む。
各 highlight に quote_draft(引用 RT 用)と own_post_draft(別投稿用)を生成。

dispatcher は Discord 通信を持たない(テスト容易性)。
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

from . import repo, x_client

log = logging.getLogger("hajime-ai-bot.curation.digester")

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 2000

_PERSONA_PATH = Path(__file__).resolve().parents[3] / "prompts" / "persona.yaml"
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config.yaml"


@dataclass
class CurationHighlight:
    tweet_id: str
    author_handle: str
    text: str
    why_relevant: str
    quote_draft: str       # 引用 RT に添える一言 30-60 字目安
    url: str
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0


@dataclass
class CurationResult:
    highlights: list[CurationHighlight]
    accounts_scanned: int
    tweets_fetched: int
    errors: list[str]


class CurationError(Exception):
    pass


def _load_persona() -> dict[str, Any]:
    if not _PERSONA_PATH.exists():
        raise CurationError(f"persona.yaml が見つかりません: {_PERSONA_PATH}")
    data = yaml.safe_load(_PERSONA_PATH.read_text(encoding="utf-8")) or {}
    if "curation" not in data or "system_prompt" not in data:
        raise CurationError(
            "persona.yaml に curation / system_prompt セクションがありません"
        )
    return data


def _load_config_thresholds() -> dict[str, int]:
    """config.yaml の curation: セクションから閾値を読む。

    無い項目は安全側のデフォルトを返す。
    """
    defaults = {"hours": 24, "max_per_user": 10, "min_likes": 100, "top_n": 3}
    if not _CONFIG_PATH.exists():
        return defaults
    data = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    cfg = data.get("curation") or {}
    for k in defaults:
        v = cfg.get(k)
        if isinstance(v, int) and v > 0:
            defaults[k] = v
    return defaults


def _format_tweets_block(
    grouped: list[tuple[str, list[x_client.XTweet]]],
) -> str:
    if not grouped:
        return "(取得できた投稿はありません)"
    lines: list[str] = []
    for handle, tweets in grouped:
        lines.append(f"\n=== @{handle} ({len(tweets)} 投稿) ===")
        for t in tweets:
            metrics = f"❤{t.like_count} 🔁{t.retweet_count} 💬{t.reply_count}"
            ts = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "-"
            kind = []
            if t.is_reply:
                kind.append("reply")
            if t.is_quote:
                kind.append("quote")
            kind_str = f" [{','.join(kind)}]" if kind else ""
            body = t.text.replace("\n", " ").strip()
            lines.append(
                f"  tweet_id={t.tweet_id}{kind_str} {ts} {metrics}\n"
                f"    {body}"
            )
    return "\n".join(lines)


def run_curation(
    *,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> CurationResult:
    """active watch_accounts 全員から直近 N 時間の投稿を取得 → Claude で top 3。

    閾値は config.yaml の curation: セクションから読む。min_likes 未満の投稿は
    LLM に渡す前にフィルタ(コスト削減 + ノイズ抑制)。

    Raises
    ------
    CurationError
        active アカウントが 0 / API 鍵欠落 / Claude API 失敗。
    """
    cfg = _load_config_thresholds()
    hours = cfg["hours"]
    max_per_user = cfg["max_per_user"]
    min_likes = cfg["min_likes"]

    accounts = repo.list_active()
    if not accounts:
        raise CurationError(
            "active な watch_accounts がありません。config.yaml の watch_accounts に "
            "ハンドルを追加するか、`/hjm-watch add @handle` で追加してください。"
        )

    grouped: list[tuple[str, list[x_client.XTweet]]] = []
    tweet_index: dict[str, x_client.XTweet] = {}
    errors: list[str] = []
    total_tweets = 0

    for acct in accounts:
        handle = acct["handle"]
        try:
            user_ref, tweets = x_client.fetch_tweets_for_handle(
                handle, hours=hours, max_results=max_per_user
            )
            if not acct.get("user_id"):
                repo.update_user_id(handle, user_ref.user_id, user_ref.display_name)
            repo.set_last_fetched(handle)
            # min_likes フィルタ:バズ判定に届かない投稿は LLM に渡さない
            buzzy = [t for t in tweets if t.like_count >= min_likes]
            if buzzy:
                grouped.append((handle, buzzy))
                for t in buzzy:
                    tweet_index[t.tweet_id] = t
                total_tweets += len(buzzy)
            else:
                log.info(
                    "curation: @%s has %d tweets but none >= %d likes",
                    handle, len(tweets), min_likes,
                )
        except x_client.XClientError as e:
            log.warning("curation: fetch failed for @%s: %s", handle, e)
            errors.append(f"@{handle}: {e}")

    if total_tweets == 0:
        log.info("curation: no buzzy tweets from %d accounts", len(accounts))
        return CurationResult(
            highlights=[],
            accounts_scanned=len(accounts),
            tweets_fetched=0,
            errors=errors,
        )

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CurationError("ANTHROPIC_API_KEY が未設定です")

    persona = _load_persona()
    system_base = persona["system_prompt"]
    cur_cfg = persona["curation"]
    system_addon = cur_cfg["system_prompt_addon"]
    user_tmpl = cur_cfg["user_prompt_tmpl"]
    system_prompt = (system_base.rstrip() + "\n\n" + system_addon).strip()
    user_prompt = user_tmpl.format(tweets_block=_format_tweets_block(grouped))

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise CurationError(f"Claude API 呼び出し失敗: {e}") from e

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    raw_text = "\n".join(text_blocks)
    parsed = _extract_json(raw_text)
    if not parsed or not isinstance(parsed.get("highlights"), list):
        raise CurationError(f"JSON パース失敗 / highlights 欠落。raw len={len(raw_text)}")

    highlights: list[CurationHighlight] = []
    for raw in parsed["highlights"]:
        if not isinstance(raw, dict):
            continue
        tweet_id = str(raw.get("tweet_id", "")).strip()
        if not tweet_id or tweet_id not in tweet_index:
            log.warning("curation: highlight references unknown tweet_id=%r, skip", tweet_id)
            continue
        t = tweet_index[tweet_id]
        author_handle_raw = str(raw.get("author_handle", t.author_handle))
        quote_draft = str(raw.get("quote_draft", "")).strip()
        # 140 字超過は警告のみ(配信は続ける、dispatcher 側で字数表示)。
        # 目安は 30-60 字だが、多少長い分は許容する。
        if quote_draft and len(quote_draft) > 140:
            log.warning(
                "curation quote_draft over 140 chars (len=%d): %s...",
                len(quote_draft), quote_draft[:30],
            )
        highlights.append(
            CurationHighlight(
                tweet_id=tweet_id,
                author_handle=author_handle_raw.lstrip("@").strip(),
                text=t.text,
                why_relevant=str(raw.get("why_relevant", "")).strip(),
                quote_draft=quote_draft,
                url=t.url,
                like_count=t.like_count,
                retweet_count=t.retweet_count,
                reply_count=t.reply_count,
            )
        )

    log.info(
        "curation: accounts=%d tweets=%d highlights=%d errors=%d",
        len(accounts), total_tweets, len(highlights), len(errors),
    )
    return CurationResult(
        highlights=highlights,
        accounts_scanned=len(accounts),
        tweets_fetched=total_tweets,
        errors=errors,
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
