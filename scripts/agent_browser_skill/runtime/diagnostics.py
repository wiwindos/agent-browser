from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_browser_skill.core.artifacts import path_size
from agent_browser_skill.core.locks import (
    clear_manual_browser_lock,
    manual_browser_lock_is_stale,
    read_manual_browser_lock,
)
from agent_browser_skill.core.output import metadata
from agent_browser_skill.core.paths import last_artifact, paths_for, remembered_url
from agent_browser_skill.core.profiles import load_profile_aliases
from agent_browser_skill.core.structured_logs import tool_runs_log_path
from agent_browser_skill.version import SKILL_VERSION

from .sandbox_health import cgroup_pids_status, resource_status_line, sandbox_resources_exhausted, zombie_process_count
from agent_browser_skill.browser import desktop


def _profile_names(root: Path) -> list[str]:
    profiles_root = root / ".agent-browser" / "profiles"
    if not profiles_root.exists():
        return []
    return sorted(p.name for p in profiles_root.iterdir() if p.is_dir())


def _artifact_sites(root: Path) -> list[str]:
    artifacts_root = root / "browser-artifacts"
    if not artifacts_root.exists():
        return []
    return sorted(p.name for p in artifacts_root.iterdir() if p.is_dir())


def collect_diagnostics(root: Path, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(args or {})
    if "action" not in args:
        args["action"] = "status"
    paths = paths_for(root, args)
    manual_lock = read_manual_browser_lock(root)
    if manual_lock and manual_browser_lock_is_stale(root, manual_lock, manual_desktop_running=desktop.manual_desktop_running):
        clear_manual_browser_lock(root)
        manual_lock = None
    pids_current, pids_limit = cgroup_pids_status()
    profiles = _profile_names(root)
    artifacts = _artifact_sites(root)
    active_site = paths["site"].name
    current_artifact = last_artifact(root, active_site)
    diagnostics = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skill_version": SKILL_VERSION,
        "workspace_root": str(root),
        "workspace_size_bytes": path_size(root),
        "site_key": active_site,
        "profile": str(paths["profile"]),
        "current_artifact_dir": str(current_artifact or paths["artifact"]),
        "last_url": remembered_url(root, paths) or "",
        "profiles": profiles,
        "artifact_sites": artifacts,
        "profile_aliases": load_profile_aliases(root),
        "manual_browser_lock": manual_lock,
        "manual_desktop_running": desktop.manual_desktop_running(root),
        "resources": {
            "status_line": resource_status_line(),
            "pids_current": pids_current,
            "pids_limit": pids_limit,
            "zombies": zombie_process_count(),
            "exhausted": sandbox_resources_exhausted(),
        },
        "logs": {
            "tool_runs_jsonl": str(tool_runs_log_path(root)),
        },
    }
    diagnostics.update(metadata(paths))
    return diagnostics
