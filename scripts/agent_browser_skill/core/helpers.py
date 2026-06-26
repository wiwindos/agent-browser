from __future__ import annotations

import re
import urllib.parse


COMMON_SECOND_LEVEL_SUFFIXES = {
    "ac",
    "co",
    "com",
    "edu",
    "gov",
    "net",
    "org",
}


def safe_slug(value: str | None, default: str = "default") -> str:
    raw = (value or "").strip().lower()
    if not raw:
        raw = default
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.split("/", 1)[0]
    raw = raw.split("?", 1)[0]
    raw = raw.replace(":", "_")
    raw = re.sub(r"[^a-z0-9._-]+", "_", raw)
    raw = raw.strip("._-")
    return raw[:80] or default


def host_from_url(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    try:
        return (urllib.parse.urlparse(text).hostname or "").lower()
    except Exception:
        return ""


def base_domain(host: str) -> str:
    clean = host.strip().lower().strip(".")
    if clean.startswith("www."):
        clean = clean[4:]
    labels = [part for part in clean.split(".") if part]
    if len(labels) <= 2:
        return clean
    if (
        len(labels[-1]) == 2
        and labels[-2] in COMMON_SECOND_LEVEL_SUFFIXES
        and len(labels) >= 3
    ):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def profile_host_candidate(raw: str, raw_host: str, url_host: str) -> str:
    raw_slug = safe_slug(raw, "")
    if url_host and raw_slug and "." not in raw_slug:
        url_base = base_domain(url_host)
        if raw_slug == url_base.split(".", 1)[0] or raw_slug in url_host.split("."):
            return url_base
    return base_domain(raw_host or url_host)

