from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.browser import dashboard, desktop
from agent_browser_skill.core.args import bool_arg, timeout_from
from agent_browser_skill.core.artifacts import cleanup_note, path_size
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.core.locks import (
    clear_manual_browser_lock,
    manual_browser_lock_is_stale,
    read_manual_browser_lock,
)
from agent_browser_skill.core.output import metadata
from agent_browser_skill.core.workflow import clear_workflow_state
from agent_browser_skill.core.paths import remembered_url
from agent_browser_skill.core.profiles import (
    load_profile_aliases,
    normalize_profile_aliases,
    profile_aliases_file,
    save_profile_aliases,
)
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime import dependencies as runtime_deps
from agent_browser_skill.runtime.diagnostics import collect_diagnostics
from agent_browser_skill.runtime import process as process_runtime
from agent_browser_skill.runtime.sandbox_health import resource_status_line


def action_close(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    desktop_note = process_runtime.stop_manual_desktop(root)
    dashboard.stop_dashboard_proxy(root, dashboard.dashboard_port_from(args))
    runtime_deps.close_agent_browser(root, timeout_from(args))
    process_runtime.wait_profile_unlocked(paths["profile"], timeout=3.0)
    removed = process_runtime.unlock_profile(paths["profile"])
    suffix = f"; removed stale profile locks: {len(removed)}" if removed else ""
    clear_workflow_state(root, paths)
    return f"agent-browser daemon closed; manual_desktop: {desktop_note}{suffix}", metadata(paths)


def action_recover(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout = timeout_from(args)
    notes = []
    notes.append(process_runtime.stop_manual_desktop(root))
    runtime_deps.close_agent_browser(root, timeout)
    process_runtime.wait_profile_unlocked(paths["profile"], timeout=3.0)
    removed = process_runtime.unlock_profile(paths["profile"])
    if removed:
        notes.append(f"removed stale profile locks: {len(removed)}")
    if args.get("install"):
        notes.append(runtime_deps.install_browser_dependencies(root, timeout, args))
        binary = runtime_deps.require_agent_browser(root, args, timeout)
        code, out = process_runtime.run_process([binary, "install"], timeout=timeout, cwd=root)
        if code != 0:
            notes.append(f"agent-browser install warning: {out}")
    if not notes:
        notes.append("closed daemon; profile had no visible lock files")
    clear_workflow_state(root, paths)
    return "\n".join(notes), metadata(paths)


def action_status(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    profiles_root = root / ".agent-browser" / "profiles"
    artifacts_root = root / "browser-artifacts"
    profiles = sorted(p.name for p in profiles_root.iterdir() if p.is_dir()) if profiles_root.exists() else []
    artifacts = sorted(p.name for p in artifacts_root.iterdir() if p.is_dir()) if artifacts_root.exists() else []
    aliases = load_profile_aliases(root)
    aliases_text = ", ".join(
        f"{profile}=[{', '.join(patterns)}]" for profile, patterns in sorted(aliases.items())
    ) or "(none)"
    manual_lock = read_manual_browser_lock(root)
    if manual_lock and manual_browser_lock_is_stale(root, manual_lock, manual_desktop_running=desktop.manual_desktop_running):
        clear_manual_browser_lock(root)
        manual_lock = None
    if manual_lock:
        created = float(manual_lock.get("created_at") or 0)
        expires = float(manual_lock.get("expires_at") or 0)
        manual_lock_text = (
            f"busy profile={manual_lock.get('profile')} action={manual_lock.get('action')} "
            f"since={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created)) if created else '(unknown)'} "
            f"expires={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires)) if expires else '(unknown)'}"
        )
    else:
        manual_lock_text = "free"
    output = "\n".join(
        [
            "agent-browser skill status",
            f"profiles: {', '.join(profiles) if profiles else '(none)'}",
            f"artifact sites: {', '.join(artifacts) if artifacts else '(none)'}",
            f"current profile: {paths['profile']}",
            f"manual_browser_lock: {manual_lock_text}",
            f"last_url: {remembered_url(root, paths) or '(none)'}",
            f"cookies db: {'yes' if (paths['profile'] / 'Default' / 'Network' / 'Cookies').exists() or (paths['profile'] / 'Default' / 'Cookies').exists() else 'no'}",
            f"profile aliases: {aliases_text}",
            f"current artifact_dir: {paths['artifact']}",
            f"workspace size: {path_size(root) // 1024 // 1024}MB",
            f"process resources: {resource_status_line()}",
        ]
    )
    meta = metadata(paths)
    if manual_lock:
        meta["manual_browser_lock"] = manual_lock
    meta["diagnostics"] = collect_diagnostics(root, args)
    return output, meta


def action_profile_aliases(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    aliases = load_profile_aliases(root)
    lines = ["profile aliases"]
    for profile, patterns in sorted(aliases.items()):
        lines.append(f"{profile}: {', '.join(patterns)}")
    if len(lines) == 1:
        lines.append("(none)")
    meta = metadata(paths)
    meta["profile_aliases"] = aliases
    meta["profile_aliases_file"] = str(profile_aliases_file(root))
    return "\n".join(lines), meta


def action_set_profile_alias(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    profile = safe_slug(str(args.get("profile") or args.get("site_key") or ""))
    if not profile:
        raise ToolError("profile is required for set_profile_alias")
    domains_raw = args.get("domains") or args.get("domain") or args.get("text") or args.get("url")
    if isinstance(domains_raw, str):
        domains = [part.strip() for part in re.split(r"[,;\s]+", domains_raw) if part.strip()]
    elif isinstance(domains_raw, list):
        domains = [str(part).strip() for part in domains_raw if str(part).strip()]
    else:
        domains = []
    if not domains:
        raise ToolError("domains is required for set_profile_alias")
    aliases = load_profile_aliases(root)
    current = set(aliases.get(profile, []))
    normalized = normalize_profile_aliases({profile: domains}).get(profile, [])
    current.update(normalized)
    aliases[profile] = sorted(current)
    save_profile_aliases(root, aliases)
    meta = metadata(paths)
    meta["profile_aliases"] = aliases
    meta["profile_aliases_file"] = str(profile_aliases_file(root))
    return f"profile alias saved: {profile}: {', '.join(aliases[profile])}", meta


def action_cleanup(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    aggressive = bool_arg(args, "aggressive", False)
    include_runtime_env = bool_arg(args, "include_runtime_env", False)
    meta = metadata(paths)
    meta["cleanup_aggressive"] = aggressive
    meta["cleanup_include_runtime_env"] = include_runtime_env or aggressive
    return cleanup_note(root, aggressive=aggressive, include_runtime_env=include_runtime_env), meta
