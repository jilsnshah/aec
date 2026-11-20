"""Instagram through Meta's Graph API (Instagram Business or Creator account).

Publishing is two calls: create a media container from a public JPEG URL and
a caption, then publish the container. The container id is stored first, so
a retry after a failure publishes the same container instead of making a
second post. Accounts may publish only a limited number of posts a day; the
live quota is read from ``content_publishing_limit``.

Errors from Meta are kept word for word. An expired or revoked token (code
190) marks the connection broken: publishing pauses and the dashboard says so.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from . import integration_settings as settings_service

logger = logging.getLogger(__name__)

#: Builds the HTTP client. Tests replace it.
http_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=60)

#: Insights asked for on each post; Meta drops some over time, so missing ones are skipped.
POST_METRICS = ("reach", "views", "likes", "comments", "saved", "shares", "total_interactions")


class InstagramError(Exception):
    def __init__(self, message: str, code: Optional[int] = None, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient

    @property
    def token_broken(self) -> bool:
        return self.code == 190


class NotConnected(InstagramError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def connection(session: Session) -> Dict[str, Any]:
    row = settings_service.get(session, settings_service.INSTAGRAM)
    token = settings_service.credentials(row).get("access_token")
    cfg = row.config
    return {"enabled": bool(row.enabled and token and cfg.get("ig_user_id")), "token": token, **cfg}


def _base(conn: Dict[str, Any]) -> str:
    return "https://{}/{}".format(conn.get("api_host") or "graph.facebook.com", conn.get("graph_version") or "v23.0")


def _error(response: httpx.Response) -> InstagramError:
    try:
        err = response.json().get("error") or {}
    except ValueError:
        err = {}
    message = err.get("error_user_msg") or err.get("message") or "HTTP {}".format(response.status_code)
    code = err.get("code")
    transient = bool(err.get("is_transient")) or response.status_code >= 500 or code in (1, 2, 4, 17, 32, 341)
    return InstagramError("Instagram said: {}".format(message), code=code, transient=transient)


def _call(conn: Dict[str, Any], method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not conn.get("token") or not conn.get("ig_user_id"):
        raise NotConnected("Instagram is not connected. Add the account ID and access token in Settings → Instagram.")
    params = dict(params or {})
    try:
        with http_factory() as client:
            response = client.request(method, _base(conn) + path, params=params,
                                      headers={"Authorization": "Bearer " + conn["token"]})
    except httpx.HTTPError as exc:
        raise InstagramError("Could not reach Instagram: {}".format(exc), transient=True) from exc
    if response.status_code >= 400:
        raise _error(response)
    try:
        return response.json()
    except ValueError:
        return {}


def _mark(session: Session, error: Optional[str]) -> None:
    settings_service.record_system(session, settings_service.INSTAGRAM, last_checked_at=_now().isoformat(), last_error=error or "")


def check(session: Session) -> Dict[str, Any]:
    """Who the account is, followers, and today's publishing quota."""
    conn = connection(session)
    try:
        me = _call(conn, "GET", "/{}".format(conn["ig_user_id"]), {"fields": "username,name,followers_count,media_count"})
        quota = quota_left(session, conn)
    except InstagramError as exc:
        _mark(session, str(exc))
        raise
    settings_service.record_system(
        session, settings_service.INSTAGRAM, username=me.get("username") or "", account_name=me.get("name") or "",
        followers=int(me.get("followers_count") or 0), publish_quota=quota["total"], publish_used=quota["used"],
        last_checked_at=_now().isoformat(), last_error="",
    )
    return {"username": me.get("username"), "name": me.get("name"), "followers": me.get("followers_count"),
            "media_count": me.get("media_count"), "quota": quota}


def quota_left(session: Session, conn: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    conn = conn or connection(session)
    data = _call(conn, "GET", "/{}/content_publishing_limit".format(conn["ig_user_id"]), {"fields": "config,quota_usage"})
    row = (data.get("data") or [{}])[0]
    total = int(((row.get("config") or {}).get("quota_total")) or 50)
    used = int(row.get("quota_usage") or 0)
    return {"total": total, "used": used, "left": max(0, total - used)}


def create_container(conn: Dict[str, Any], image_url: str, caption: str) -> str:
    data = _call(conn, "POST", "/{}/media".format(conn["ig_user_id"]), {"image_url": image_url, "caption": caption})
    if not data.get("id"):
        raise InstagramError("Instagram did not return a container id.")
    return str(data["id"])


def container_status(conn: Dict[str, Any], container_id: str) -> str:
    """FINISHED, IN_PROGRESS, ERROR, EXPIRED or PUBLISHED."""
    data = _call(conn, "GET", "/{}".format(container_id), {"fields": "status_code"})
    return str(data.get("status_code") or "FINISHED")


def publish_container(conn: Dict[str, Any], container_id: str) -> Dict[str, Any]:
    data = _call(conn, "POST", "/{}/media_publish".format(conn["ig_user_id"]), {"creation_id": container_id})
    media_id = str(data.get("id") or "")
    if not media_id:
        raise InstagramError("Instagram did not return the post id.")
    permalink = None
    try:
        permalink = _call(conn, "GET", "/{}".format(media_id), {"fields": "permalink"}).get("permalink")
    except InstagramError:
        pass
    return {"id": media_id, "permalink": permalink}


def media_metrics(conn: Dict[str, Any], media_id: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    basic = _call(conn, "GET", "/{}".format(media_id), {"fields": "like_count,comments_count,permalink"})
    out["likes"] = int(basic.get("like_count") or 0)
    out["comments"] = int(basic.get("comments_count") or 0)
    try:
        data = _call(conn, "GET", "/{}/insights".format(media_id), {"metric": ",".join(POST_METRICS)})
        for item in data.get("data") or []:
            values = item.get("values") or [{}]
            value = item.get("total_value", {}).get("value") if item.get("total_value") else values[0].get("value")
            if value is not None:
                out[item.get("name")] = int(value)
    except InstagramError as exc:
        # Some metrics are unavailable for some posts/accounts; keep what we have.
        logger.info("Insights for %s unavailable: %s", media_id, exc)
    return out


def comments(conn: Dict[str, Any], media_id: str) -> List[Dict[str, Any]]:
    data = _call(conn, "GET", "/{}/comments".format(media_id), {"fields": "id,text,username,timestamp", "limit": 50})
    return list(data.get("data") or [])


def reply(conn: Dict[str, Any], comment_id: str, message: str) -> str:
    data = _call(conn, "POST", "/{}/replies".format(comment_id), {"message": message})
    return str(data.get("id") or "")


def hide(conn: Dict[str, Any], comment_id: str, hidden: bool = True) -> None:
    _call(conn, "POST", "/{}".format(comment_id), {"hide": "true" if hidden else "false"})
