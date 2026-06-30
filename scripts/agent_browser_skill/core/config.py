from __future__ import annotations

MAX_TIMEOUT = 120
DEFAULT_TIMEOUT = 60
BROWSER_TOOL_LOCK_WAIT_SECONDS = 8
WORKSPACE_SOFT_LIMIT_BYTES = 460 * 1024 * 1024
WORKSPACE_TARGET_BYTES = 420 * 1024 * 1024

DEFAULT_PROFILE_ALIASES: dict[str, list[str]] = {
    "saby": ["saby.ru", "*.saby.ru"],
}

FOLLOW_ACTIVE_PROFILE_ACTIONS = {
    "snapshot",
    "click",
    "fill",
    "type",
    "wait",
    "screenshot",
    "evaluate",
    "downloads",
    "saby_tenders_csv",
    "batch",
    "share_session",
    "desktop_open",
    "desktop_snapshot",
    "desktop_screenshot",
    "page_markdown.act",
    "challenge_detected",
    "continue_after_manual",
    "status",
}

ARTIFACT_ACTIONS = {
    "skills",
    "open",
    "snapshot",
    "click",
    "fill",
    "type",
    "wait",
    "screenshot",
    "share_session",
    "manual_desktop",
    "desktop_screenshot",
    "page_markdown",
    "page_markdown.act",
    "read_page_md",
    "click_handle",
    "fill_handle",
    "select_handle",
    "evaluate",
    "saby_tenders_csv",
    "challenge_detected",
    "continue_after_manual",
    "batch",
    "run",
    "login",
}

NEW_ARTIFACT_ACTIONS = {
    "open",
    "login",
    "manual_desktop",
    "challenge_detected",
}

KEEP_EMPTY_ARTIFACT_DIRS = 20
LOCK_STALE_SECONDS = 900
MANUAL_BROWSER_LOCK_TTL_SECONDS = 45 * 60
MANUAL_BROWSER_ACQUIRE_ACTIONS = {"manual_desktop", "login", "challenge_detected", "desktop_open", "saby_tenders_csv"}
MANUAL_BROWSER_SAME_PROFILE_ALLOWED_ACTIONS = {
    "manual_desktop",
    "challenge_detected",
    "continue_after_manual",
    "close_manual_access",
    "desktop_open",
    "desktop_snapshot",
    "desktop_screenshot",
    "page_markdown",
    "page_markdown.act",
    "read_page_md",
    "click_handle",
    "fill_handle",
    "select_handle",
    "evaluate",
    "saby_tenders_csv",
}
MANUAL_BROWSER_RELEASE_ACTIONS = {"stop_desktop", "close", "recover", "close_manual_access"}
MANUAL_BROWSER_PROFILE_ACTIONS = {
    "manual_desktop",
    "login",
    "challenge_detected",
    "continue_after_manual",
    "close_manual_access",
    "desktop_open",
    "desktop_snapshot",
    "desktop_screenshot",
    "page_markdown",
    "page_markdown.act",
    "read_page_md",
    "click_handle",
    "fill_handle",
    "select_handle",
    "evaluate",
    "saby_tenders_csv",
}
LOCKLESS_ACTIONS = {"status", "profile_aliases", "cleanup"}
