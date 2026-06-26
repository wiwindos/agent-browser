from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.core.profiles import ensure_active_profile
from agent_browser_skill.core.patterns import CHROME_RECOVERY_RE, RESOURCE_EXHAUSTED_RE
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime import sandbox_health
from agent_browser_skill.runtime.dependencies import close_agent_browser, install_browser_dependencies, require_agent_browser
from agent_browser_skill.runtime.process import run_process, unlock_profile


def bootstrap_runtime(root: Path, timeout: int) -> None:
    if shutil.which("agent-browser"):
        return

    if not shutil.which("npm"):
        if shutil.which("apt-get"):
            code, out = run_process(
                ["sh", "-lc", "apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates"],
                timeout=timeout,
                cwd=root,
            )
            if code != 0:
                raise ToolError(f"failed to install node/npm: {out}")
        else:
            raise ToolError("npm is missing and apt-get is not available")

    npm_prefix = root / ".agent-browser" / "npm-global"
    npm_prefix.mkdir(parents=True, exist_ok=True)
    env = {
        "NPM_CONFIG_PREFIX": str(npm_prefix),
        "PATH": f"{npm_prefix / 'bin'}:{os.environ.get('PATH', '')}",
    }
    code, out = run_process(
        ["npm", "install", "-g", "agent-browser"],
        timeout=timeout,
        cwd=root,
        env_extra=env,
    )
    os.environ["PATH"] = env["PATH"]
    if code != 0:
        raise ToolError(f"failed to install agent-browser: {out}")

    code, out = run_process(["agent-browser", "install"], timeout=timeout, cwd=root, env_extra=env)
    if code != 0:
        raise ToolError(f"agent-browser installed, but browser install failed: {out}")


def agent_browser_base(paths: dict[str, Path]) -> list[str]:
    return [
        "agent-browser",
        "--profile",
        str(paths["profile"]),
        "--download-path",
        str(paths["downloads"]),
    ]


def ab(
    root: Path,
    paths: dict[str, Path],
    args: dict[str, Any],
    subcommand: list[str],
    *,
    input_json: Any | None = None,
) -> tuple[int, str]:
    timeout = timeout_from(args)
    require_agent_browser(root, args, timeout)
    profile_note = ensure_active_profile(root, paths, timeout, close_agent_browser)
    command = agent_browser_base(paths) + subcommand
    input_text = json.dumps(input_json, ensure_ascii=False) if input_json is not None else None
    code, out = run_process(command, timeout=timeout, cwd=root, input_text=input_text)
    if profile_note and code == 0:
        out = "\n".join(part for part in (profile_note, out) if part)
    if code == 0 or not CHROME_RECOVERY_RE.search(out):
        return code, out

    close_agent_browser(root, timeout)
    unlocked = unlock_profile(paths["profile"])
    recovery_notes: list[str] = []
    if unlocked:
        recovery_notes.append(f"removed stale profile locks: {len(unlocked)}")
    if RESOURCE_EXHAUSTED_RE.search(out) or sandbox_health.sandbox_resources_exhausted():
        return code, (
            f"{out}\n\n"
            "recovery stopped: sandbox process resources are exhausted "
            f"({sandbox_health.resource_status_line()}). Restart this user's sandbox/container; "
            "installing packages or launching another Chrome will make it worse."
        )
    try:
        recovery_notes.append(install_browser_dependencies(root, timeout, args))
    except ToolError as exc:
        return code, f"{out}\n\nrecovery failed: {exc}"

    binary = require_agent_browser(root, args, timeout)
    install_code, install_out = run_process([binary, "install"], timeout=timeout, cwd=root)
    if install_code != 0:
        recovery_notes.append(f"agent-browser install warning: {install_out}")

    close_agent_browser(root, timeout)
    unlock_profile(paths["profile"])
    retry_code, retry_out = run_process(command, timeout=timeout, cwd=root, input_text=input_text)
    if retry_code == 0:
        prefix = "\n".join(f"recovery: {note}" for note in recovery_notes)
        return retry_code, "\n".join(part for part in (prefix, retry_out) if part)
    return retry_code, f"{retry_out}\n\nprevious error before recovery:\n{out}"
