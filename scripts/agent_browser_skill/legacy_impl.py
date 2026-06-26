#!/usr/bin/env python3
"""Backward-compatible re-export layer for the refactored agent-browser skill.

The old monolithic implementation has been decomposed into `core/*`, `runtime/*`,
`browser/*`, and `actions_*` modules. This file intentionally stays small and
only re-exports stable names for callers that still import `legacy_impl`.
"""

from __future__ import annotations

from agent_browser_skill.actions_generic import action_open, action_snapshot
from agent_browser_skill.actions_manual import action_manual_desktop
from agent_browser_skill.browser.cdp import cdp_call, cdp_eval, cdp_page_ws, cdp_tabs, ws_recv_frame, ws_send_frame
from agent_browser_skill.browser.dashboard import (
    base_public_url,
    dashboard_command,
    dashboard_internal_port_from,
    dashboard_port_from,
    dashboard_url,
    novnc_url,
    public_host_from,
    start_dashboard,
    start_dashboard_proxy,
    stop_dashboard_proxy,
)
from agent_browser_skill.browser.desktop import (
    configure_chrome_downloads,
    current_snapshot,
    desktop_cdp_port_from,
    desktop_dir,
    desktop_navigate,
    desktop_page_state,
    find_chrome_binary,
    manual_access_password,
    manual_access_running,
    manual_desktop_running,
    save_challenge_screenshot,
    screenshot_path,
    snapshot_needs_manual_action,
    state_has_usable_page,
    state_needs_manual_action,
    state_snapshot,
    wait_for_clear_desktop_page,
    write_challenge_checkpoint,
)
from agent_browser_skill.core import config as core_config
from agent_browser_skill.core.args import bool_arg, int_arg, lock_wait_seconds_from, timeout_from
from agent_browser_skill.core.artifacts import (
    active_artifact_paths,
    artifact_dirs,
    auto_cleanup_if_needed,
    cleanup_browser_artifacts,
    cleanup_empty_artifacts,
    cleanup_note,
    cleanup_profile_caches,
    cleanup_runtime_caches,
    path_size,
)
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.core.locks import (
    BrowserToolLock,
    browser_tool_busy_output,
    clear_manual_browser_lock,
    guard_manual_browser_resource,
    manual_browser_busy_output,
    manual_browser_lock_file,
    manual_browser_lock_is_stale,
    read_manual_browser_lock,
    refresh_manual_browser_lock,
    release_manual_browser_if_needed,
    write_manual_browser_lock,
)
from agent_browser_skill.core.output import cap_output, emit, load_request, metadata, pid_running, redact, workspace_root
from agent_browser_skill.core.paths import ensure_inside, remember_url, remembered_url
from agent_browser_skill.core.patterns import (
    APT_LOCK_RE,
    CHALLENGE_RE,
    CHROME_RECOVERY_RE,
    MANUAL_REQUIRED_RE,
    RESOURCE_EXHAUSTED_RE,
    SENSITIVE_RE,
)
from agent_browser_skill.core.profiles import (
    load_profile_aliases,
    normalize_profile_aliases,
    profile_aliases_file,
    save_profile_aliases,
)
from agent_browser_skill.errors import BrowserBusyError, ToolError
from agent_browser_skill.result import ToolResult
from agent_browser_skill.runtime.bootstrap import ab, agent_browser_base, bootstrap_runtime
from agent_browser_skill.runtime.constants import CHROME_DEPS_BASE, CHROME_DEPS_T64, DESKTOP_DEPS, DESKTOP_RUNTIME_BINARIES
from agent_browser_skill.runtime.dependencies import (
    apt_get_command,
    chrome_binary_exists,
    chrome_runtime_ready,
    clear_deps_marker,
    close_agent_browser,
    deps_marker,
    desktop_runtime_ready,
    install_agent_browser_chrome,
    install_browser_dependencies,
    install_desktop_dependencies,
    missing_desktop_runtime_components,
    require_agent_browser,
    write_deps_marker,
)
from agent_browser_skill.runtime.process import run_process, start_bg, stop_manual_access, stop_manual_desktop, stop_pid_file, unlock_profile, wait_profile_unlocked
from agent_browser_skill.runtime.sandbox_health import cgroup_pids_status, read_int_file, resource_status_line, sandbox_resources_exhausted, zombie_process_count
from agent_browser_skill.version import SKILL_VERSION

MAX_TIMEOUT = core_config.MAX_TIMEOUT
DEFAULT_TIMEOUT = core_config.DEFAULT_TIMEOUT
BROWSER_TOOL_LOCK_WAIT_SECONDS = core_config.BROWSER_TOOL_LOCK_WAIT_SECONDS
WORKSPACE_SOFT_LIMIT_BYTES = core_config.WORKSPACE_SOFT_LIMIT_BYTES
WORKSPACE_TARGET_BYTES = core_config.WORKSPACE_TARGET_BYTES
KEEP_EMPTY_ARTIFACT_DIRS = core_config.KEEP_EMPTY_ARTIFACT_DIRS


__all__ = [name for name in globals() if not name.startswith("_")]
