from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agent_browser_skill.actions_manual import action_manual_desktop
from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.core.locks import clear_manual_browser_lock
from agent_browser_skill.core.output import metadata
from agent_browser_skill.core.paths import ensure_inside
from agent_browser_skill.core.workflow import build_browser_workflow
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime import dependencies as runtime_deps
from agent_browser_skill.runtime import process as process_runtime


def action_login(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not args.get("url"):
        raise ToolError("url is required for login")
    manual_args = dict(args)
    manual_args.setdefault("handoff", "manual_desktop")
    output, meta = action_manual_desktop(root, paths, manual_args)
    continue_args = {"profile": paths["site"].name}
    current_url = str(meta.get("current_url") or args.get("url") or "").strip()
    if current_url:
        continue_args["url"] = current_url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if meta.get("user_action_required", True) else "page_ready",
            user_action_required=bool(meta.get("user_action_required", True)),
            recommended_next_action=str(meta.get("recommended_next_action") or "continue_after_manual"),
            recommended_next_args=dict(meta.get("recommended_next_args") or continue_args),
            next_tool_call=dict(meta.get("next_tool_call") or {"action": "continue_after_manual", **continue_args}),
            external_urls=dict(meta.get("external_urls") or {}),
            credentials_to_show_user=dict(meta.get("credentials_to_show_user") or {}),
            user_message_hint="Use the manual browser session only if the page still needs user interaction. Never ask the user to paste credentials into chat.",
        )
    )
    note = "\n".join(
        [
            "manual login session opened with persistent profile",
            f"profile: {paths['profile']}",
            "Send the noVNC URL and vnc_passcode to the user. They must enter credentials manually.",
            "Never ask the user to send passwords or OTPs in chat.",
            "next_step: wait for the user's next completion confirmation message, then call continue_after_manual with the same profile/site_key.",
            "After the user's next confirmation message, call continue_after_manual with the same profile/site_key. Do not require an exact trigger word.",
            output,
        ]
    )
    return note, meta


def action_clear_session(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    runtime_deps.close_agent_browser(root, timeout_from(args))
    process_runtime.stop_manual_desktop(root)
    clear_manual_browser_lock(root)
    profile = ensure_inside(paths["profile"], root)
    if profile.exists():
        shutil.rmtree(profile)
    profile.mkdir(parents=True, exist_ok=True)
    meta = metadata(paths)
    meta["manual_browser_lock_released"] = True
    return f"cleared browser session: {profile}", meta

