#!/usr/bin/env python3
"""Thin entrypoint for the LocalTopSH agent-browser skill."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_browser_skill.actions import ACTIONS, metadata
from agent_browser_skill import actions_auth, actions_saby
from agent_browser_skill.browser import desktop as desktop_helpers
from agent_browser_skill.core.args import bool_arg, lock_wait_seconds_from, timeout_from
from agent_browser_skill.core.artifacts import cleanup_browser_artifacts, path_size
from agent_browser_skill.core.config import BROWSER_TOOL_LOCK_WAIT_SECONDS
from agent_browser_skill.core import locks as core_locks
from agent_browser_skill.core.output import cap_output, emit, load_request, pid_running, redact
from agent_browser_skill.core.paths import ensure_inside, paths_for, remember_url, remembered_url
from agent_browser_skill.core.profiles import canonical_profile_key, load_profile_aliases, save_profile_aliases
from agent_browser_skill.errors import BrowserBusyError, ToolError
from agent_browser_skill.actions_manual import action_manual_desktop
from agent_browser_skill.browser.desktop import manual_desktop_running
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.core.output import workspace_root
from agent_browser_skill.result import ToolResult as CoreToolResult
from agent_browser_skill.version import SKILL_VERSION
from agent_browser_skill.runner import main as runner_main, run_request as runner_run_request


class BrowserToolLock(core_locks.BrowserToolLock):
    def __init__(self, root, action, timeout=BROWSER_TOOL_LOCK_WAIT_SECONDS):
        super().__init__(root, action, timeout, pid_running=pid_running)


class ToolResult(CoreToolResult):
    def to_payload(self, *, redact=redact, cap_output=cap_output):
        return super().to_payload(redact=redact, cap_output=cap_output)


def manual_browser_lock_is_stale(root, lock):
    return core_locks.manual_browser_lock_is_stale(
        root,
        lock,
        manual_desktop_running=manual_desktop_running,
    )


manual_browser_lock_file = core_locks.manual_browser_lock_file
read_manual_browser_lock = core_locks.read_manual_browser_lock
refresh_manual_browser_lock = core_locks.refresh_manual_browser_lock
clear_manual_browser_lock = core_locks.clear_manual_browser_lock
release_manual_browser_if_needed = core_locks.release_manual_browser_if_needed


def write_manual_browser_lock(root, paths, args, action):
    return core_locks.write_manual_browser_lock(
        root,
        paths,
        args,
        action,
        remembered_url=remembered_url,
    )


def guard_manual_browser_resource(root, paths, args, action):
    return core_locks.guard_manual_browser_resource(
        root,
        paths,
        args,
        action,
        manual_desktop_running=manual_desktop_running,
        bool_arg=bool_arg,
        remembered_url=remembered_url,
    )


def run_request(request):
    desktop_helpers.manual_desktop_running = manual_desktop_running
    actions_saby.action_manual_desktop = action_manual_desktop
    actions_auth.action_manual_desktop = action_manual_desktop
    return runner_run_request(request)


def main():
    desktop_helpers.manual_desktop_running = manual_desktop_running
    actions_saby.action_manual_desktop = action_manual_desktop
    actions_auth.action_manual_desktop = action_manual_desktop
    return runner_main()


__all__ = [
    "ACTIONS",
    "BrowserBusyError",
    "BrowserToolLock",
    "SKILL_VERSION",
    "ToolError",
    "ToolResult",
    "bool_arg",
    "cap_output",
    "canonical_profile_key",
    "cleanup_browser_artifacts",
    "clear_manual_browser_lock",
    "emit",
    "ensure_inside",
    "guard_manual_browser_resource",
    "load_profile_aliases",
    "load_request",
    "lock_wait_seconds_from",
    "main",
    "manual_desktop_running",
    "manual_browser_lock_file",
    "manual_browser_lock_is_stale",
    "metadata",
    "path_size",
    "paths_for",
    "pid_running",
    "read_manual_browser_lock",
    "redact",
    "refresh_manual_browser_lock",
    "release_manual_browser_if_needed",
    "remember_url",
    "remembered_url",
    "run_request",
    "safe_slug",
    "save_profile_aliases",
    "timeout_from",
    "workspace_root",
    "write_manual_browser_lock",
]


if __name__ == "__main__":
    raise SystemExit(main())
