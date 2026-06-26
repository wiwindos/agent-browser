from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .config import DEFAULT_PROFILE_ALIASES, FOLLOW_ACTIVE_PROFILE_ACTIONS
from .helpers import host_from_url, profile_host_candidate, safe_slug


def profile_aliases_file(root: Path) -> Path:
    return root / ".agent-browser" / "profile-aliases.json"


def active_profile_file(root: Path) -> Path:
    path = root / ".agent-browser" / "active-profile"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_profile_aliases(raw: Any) -> dict[str, list[str]]:
    if isinstance(raw, dict) and isinstance(raw.get("profiles"), dict):
        raw = raw["profiles"]
    if not isinstance(raw, dict):
        return {}
    aliases: dict[str, list[str]] = {}
    for profile, patterns in raw.items():
        profile_key = safe_slug(str(profile))
        if not profile_key:
            continue
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            continue
        clean_patterns: list[str] = []
        for pattern in patterns:
            text = str(pattern or "").strip().lower()
            if not text:
                continue
            if text.startswith("*."):
                host = host_from_url(text[2:]) or safe_slug(text[2:])
                clean_patterns.append(f"*.{host}")
            else:
                host = host_from_url(text) or safe_slug(text)
                clean_patterns.append(host)
        if clean_patterns:
            aliases[profile_key] = sorted(set(clean_patterns))
    return aliases


def load_profile_aliases(root: Path | None = None) -> dict[str, list[str]]:
    aliases = {profile: list(patterns) for profile, patterns in DEFAULT_PROFILE_ALIASES.items()}
    if root is None:
        return aliases
    path = profile_aliases_file(root)
    if not path.exists():
        return aliases
    try:
        user_aliases = normalize_profile_aliases(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return aliases
    for profile, patterns in user_aliases.items():
        aliases[profile] = sorted(set([*aliases.get(profile, []), *patterns]))
    return aliases


def save_profile_aliases(root: Path, aliases: dict[str, list[str]]) -> None:
    path = profile_aliases_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"profiles": normalize_profile_aliases(aliases)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def alias_matches_host(pattern: str, host: str) -> bool:
    pattern = pattern.strip().lower()
    host = host.strip().lower()
    if not pattern or not host:
        return False
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    return host == pattern


def profile_alias_for_host(host: str, aliases: dict[str, list[str]]) -> str:
    for profile, patterns in aliases.items():
        if any(alias_matches_host(pattern, host) for pattern in patterns):
            return profile
    return ""


def active_site_key(root: Path | None) -> str:
    if root is None:
        return ""
    marker = active_profile_file(root)
    if not marker.exists():
        return ""
    try:
        profile_path = marker.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not profile_path:
        return ""
    return safe_slug(Path(profile_path).name)


def canonical_profile_key(value: str | None, url: str | None = None, root: Path | None = None) -> str:
    raw = (value or "").strip()
    raw_host = host_from_url(raw)
    url_host = host_from_url(url)
    host = profile_host_candidate(raw, raw_host, url_host)
    aliases = load_profile_aliases(root)
    alias = (
        profile_alias_for_host(raw_host, aliases)
        or profile_alias_for_host(url_host, aliases)
        or profile_alias_for_host(host, aliases)
    )
    if alias:
        return alias
    return safe_slug(host or raw or url or "default")


def site_key_from(args: dict[str, Any], root: Path | None = None) -> str:
    action = str(args.get("action") or "")
    active = active_site_key(root) if action in FOLLOW_ACTIVE_PROFILE_ACTIONS else ""
    if args.get("profile"):
        profile_value = str(args["profile"])
        if safe_slug(profile_value, "default") == "default" and args.get("url"):
            return canonical_profile_key(str(args.get("url") or "default"), root=root)
        if not args.get("url") and active:
            raw_slug = safe_slug(profile_value, "")
            if raw_slug == active or raw_slug == active.split(".", 1)[0] or raw_slug in active.split("."):
                return active
        return canonical_profile_key(profile_value, str(args.get("url") or ""), root)
    if args.get("site_key"):
        return canonical_profile_key(str(args["site_key"]), str(args.get("url") or ""), root)
    if args.get("url"):
        return canonical_profile_key(str(args.get("url") or "default"), root=root)
    if active:
        return active
    return "default"


def ensure_active_profile(
    root: Path,
    paths: dict[str, Path],
    timeout: int,
    close_agent_browser: Callable[[Path, int], str],
) -> str:
    marker = active_profile_file(root)
    current = str(paths["profile"])
    previous = marker.read_text(encoding="utf-8", errors="replace").strip() if marker.exists() else ""
    if previous and previous != current:
        close_agent_browser(root, timeout)
        marker.write_text(current, encoding="utf-8")
        return f"switched profile: closed previous daemon for {previous}"
    marker.write_text(current, encoding="utf-8")
    return ""
