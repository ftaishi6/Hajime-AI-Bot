"""X API v2 read-only クライアント(キュレーション用)。

Xapp の watch.x_client を簡略化(本リポでは Bearer Token のみサポート、
OAuth 1.0a フォールバックは使わない)。

責務:
- handle → user_id 引き
- user_id → 直近 N 時間のツイート取得
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("hajime-ai-bot.curation.x_client")

DEFAULT_FETCH_HOURS = 24
DEFAULT_MAX_TWEETS_PER_USER = 10
TWEET_FIELDS = ("created_at", "public_metrics", "lang", "referenced_tweets")
USER_FIELDS = ("username", "name", "verified", "public_metrics")


@dataclass(frozen=True)
class XUserRef:
    user_id: str
    handle: str
    display_name: str | None = None


@dataclass(frozen=True)
class XTweet:
    tweet_id: str
    author_handle: str
    author_user_id: str
    text: str
    created_at: datetime
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    lang: str | None = None
    is_retweet: bool = False
    is_reply: bool = False
    is_quote: bool = False

    @property
    def url(self) -> str:
        return f"https://x.com/{self.author_handle}/status/{self.tweet_id}"


class XClientError(Exception):
    pass


def _build_client():
    import tweepy  # noqa: PLC0415

    bearer = os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        raise XClientError(
            "X_BEARER_TOKEN が未設定です。/opt/hajime-ai-bot/.env を確認してください。"
        )
    return tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)


def lookup_user(handle: str) -> XUserRef:
    handle = handle.lstrip("@").strip()
    if not handle:
        raise XClientError("handle が空です")

    client = _build_client()
    try:
        res = client.get_user(username=handle, user_fields=list(USER_FIELDS))
    except Exception as e:
        raise XClientError(f"users/by/username 呼び出し失敗 ({handle}): {e}") from e

    if not res or not getattr(res, "data", None):
        raise XClientError(f"ユーザーが見つかりません: {handle}")
    data = res.data
    return XUserRef(
        user_id=str(data.id),
        handle=data.username,
        display_name=getattr(data, "name", None),
    )


def fetch_recent_tweets(
    user_id: str,
    *,
    hours: int = DEFAULT_FETCH_HOURS,
    max_results: int = DEFAULT_MAX_TWEETS_PER_USER,
) -> list[XTweet]:
    if hours <= 0:
        raise XClientError("hours must be positive")
    if max_results < 5:
        max_results = 5
    elif max_results > 100:
        max_results = 100

    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    client = _build_client()
    try:
        res = client.get_users_tweets(
            id=user_id,
            max_results=max_results,
            start_time=start_time,
            tweet_fields=list(TWEET_FIELDS),
            exclude=["retweets"],
        )
    except Exception as e:
        raise XClientError(f"users/:id/tweets 失敗 (user_id={user_id}): {e}") from e

    out: list[XTweet] = []
    data = getattr(res, "data", None) or []
    for t in data:
        metrics: dict[str, Any] = getattr(t, "public_metrics", None) or {}
        refs = getattr(t, "referenced_tweets", None) or []
        ref_types = {r.get("type") if isinstance(r, dict) else r.type for r in refs}
        out.append(
            XTweet(
                tweet_id=str(t.id),
                author_handle="",
                author_user_id=str(user_id),
                text=t.text or "",
                created_at=t.created_at,
                like_count=int(metrics.get("like_count", 0)),
                retweet_count=int(metrics.get("retweet_count", 0)),
                reply_count=int(metrics.get("reply_count", 0)),
                quote_count=int(metrics.get("quote_count", 0)),
                lang=getattr(t, "lang", None),
                is_retweet="retweeted" in ref_types,
                is_reply="replied_to" in ref_types,
                is_quote="quoted" in ref_types,
            )
        )
    log.info(
        "fetched %d tweets for user_id=%s (window=%dh, max=%d)",
        len(out), user_id, hours, max_results,
    )
    return out


def fetch_tweets_for_handle(
    handle: str,
    *,
    hours: int = DEFAULT_FETCH_HOURS,
    max_results: int = DEFAULT_MAX_TWEETS_PER_USER,
) -> tuple[XUserRef, list[XTweet]]:
    user = lookup_user(handle)
    tweets = fetch_recent_tweets(user.user_id, hours=hours, max_results=max_results)
    from dataclasses import replace  # noqa: PLC0415
    tweets = [replace(t, author_handle=user.handle) for t in tweets]
    return user, tweets
