from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.browser import cdp, desktop
from agent_browser_skill.browser.desktop import screenshot_path
from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.core import locks as core_locks
from agent_browser_skill.core.output import cap_output, metadata, success_or_raise
from agent_browser_skill.core.paths import remember_url
from agent_browser_skill.core.snapshot_artifacts import compact_excerpt, parse_snapshot_json, write_json_artifact, write_text_artifact
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime.bootstrap import ab
from agent_browser_skill.runtime import dependencies as runtime_deps
from agent_browser_skill.runtime.process import run_process, unlock_profile


def _snapshot_empty(parsed: dict[str, Any], refs_count: int) -> bool:
    title = str(parsed.get("title") or "").strip().lower()
    return refs_count == 0 or title in {"", "(unknown)", "unknown", "none", "null"}


def _empty_snapshot_guidance(snapshot_file: Path) -> list[str]:
    next_tool_call = {"action": "read_artifact", "path": str(snapshot_file)}
    return [
        (
            "next_step: Snapshot is empty or has no usable refs/title. "
            "Call action=read_artifact with the exact snapshot_file path. "
            "Do not pass the artifact directory."
        ),
        f"next_tool_call: {json.dumps(next_tool_call, ensure_ascii=False)}",
        (
            "fallback_after_read: If the artifact is still unusable, call action=desktop_open "
            "with the same profile/url, then action=desktop_snapshot. Do not call screenshot "
            "as recovery unless explicitly requested."
        ),
    ]


def action_start(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout = timeout_from(args)
    bootstrap_notes = []
    binary = runtime_deps.require_agent_browser(root, args, timeout)
    if args.get("install"):
        runtime_deps.close_agent_browser(root, timeout)
        removed = unlock_profile(paths["profile"])
        if removed:
            bootstrap_notes.append(f"removed stale profile locks: {len(removed)}")
        bootstrap_notes.append(runtime_deps.install_browser_dependencies(root, timeout, args))
        binary = runtime_deps.require_agent_browser(root, args, timeout)
        install_code, install_out = run_process([binary, "install"], timeout=timeout, cwd=root)
        if install_code != 0:
            bootstrap_notes.append(f"agent-browser install warning: {install_out}")
    code, version = run_process([binary, "--version"], timeout=15, cwd=root)
    if code != 0:
        version = "agent-browser found, but --version failed: " + version
    output = "\n".join(
        [
            "agent-browser runtime ready",
            f"binary: {binary}",
            f"version: {version.strip()}",
            f"profile: {paths['profile']}",
            f"artifact_dir: {paths['artifact']}",
            *[f"bootstrap: {note}" for note in bootstrap_notes],
        ]
    )
    return output, metadata(paths)


def action_skills(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    skill = safe_slug(str(args.get("skill") or "core"), "core")
    cmd = ["skills", "get", skill]
    if args.get("full"):
        cmd.append("--full")
    code, out = ab(root, paths, args, cmd)
    return cap_output(success_or_raise(code, out)), metadata(paths)


def _manual_desktop_same_profile(root: Path, paths: dict[str, Path]) -> bool:
    if not desktop.manual_desktop_running(root):
        return False
    lock = core_locks.read_manual_browser_lock(root)
    if lock and core_locks.manual_browser_lock_is_stale(root, lock, manual_desktop_running=desktop.manual_desktop_running):
        core_locks.clear_manual_browser_lock(root)
        lock = None
    if not lock:
        return False
    return str(lock.get("profile") or "") == paths["site"].name


def _desktop_state_artifacts(root: Path, paths: dict[str, Path], prefix: str, state: dict[str, Any]) -> tuple[Path, Path]:
    state_file = write_json_artifact(root, paths, prefix, state)
    text_file = write_text_artifact(root, paths, f"{prefix}-text", str(state.get("text") or ""))
    return state_file, text_file


def _desktop_summary(prefix: str, state: dict[str, Any], state_file: Path, text_file: Path, challenge: bool) -> str:
    return "\n".join(
        [
            f"{prefix}=true",
            f"challenge_detected: {str(challenge).lower()}",
            f"current_url: {state.get('url')}",
            f"title: {state.get('title')}",
            f"html_length: {state.get('htmlLength')}",
            f"text_length: {len(str(state.get('text') or ''))}",
            f"text_excerpt: {compact_excerpt(state.get('text') or '', 500)}",
            f"state_file: {state_file}",
            f"text_file: {text_file}",
        ]
    )


def _desktop_snapshot_payload(root: Path, paths: dict[str, Path], args: dict[str, Any], prefix: str) -> tuple[str, dict[str, Any]]:
    state = desktop.desktop_page_state(args)
    challenge = desktop.state_needs_manual_action(state)
    state_file, text_file = _desktop_state_artifacts(root, paths, prefix, state)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "challenge_detected": challenge,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    return _desktop_summary(prefix, state, state_file, text_file, challenge), meta


def _desktop_eval_click(selector: str) -> str:
    if selector.startswith("text="):
        needle = selector.split("=", 1)[1].strip()
        return f"""
(() => {{
  const needle = {needle!r};
  const nodes = Array.from(document.querySelectorAll('a,button,div,span,label,li,[role="button"],[tabindex]'));
  const match = nodes.find((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().includes(needle));
  if (!match) return {{ clicked: false, reason: 'not_found' }};
  match.scrollIntoView({{ block: 'center', inline: 'center' }});
  match.click();
  return {{ clicked: true, text: (match.innerText || match.textContent || '').trim().slice(0, 200) }};
}})()
"""
    return f"""
(() => {{
  const el = document.querySelector({selector!r});
  if (!el) return {{ clicked: false, reason: 'not_found' }};
  el.scrollIntoView({{ block: 'center', inline: 'center' }});
  el.click();
  return {{ clicked: true, text: (el.innerText || el.textContent || '').trim().slice(0, 200) }};
}})()
"""


def _desktop_eval_wait(args: dict[str, Any]) -> tuple[str, float]:
    timeout = float(timeout_from(args))
    deadline = time.time() + max(1.0, timeout)
    poll = 0.5
    if args.get("wait_until"):
        kind = "load"
        needle = str(args["wait_until"])
        expr = "document.readyState"
    elif args.get("url"):
        kind = "url"
        needle = str(args["url"])
        expr = "location.href"
    elif args.get("text"):
        text = str(args["text"])
        if text.isdigit():
            return "sleep", min(max(int(text), 0), 30000) / 1000.0
        kind = "text"
        needle = text
        expr = "document.body ? document.body.innerText : ''"
    elif args.get("selector"):
        kind = "selector"
        needle = str(args["selector"])
        expr = f"!!document.querySelector({needle!r})"
    else:
        return "sleep", 1.0
    return json.dumps({"kind": kind, "needle": needle, "expr": expr, "deadline": deadline}), poll


def action_open(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    if not url:
        raise ToolError("url is required for open")
    remember_url(root, paths, url)
    if _manual_desktop_same_profile(root, paths):
        desktop.desktop_navigate(args, url)
        time.sleep(1.5)
        return _desktop_snapshot_payload(root, paths, args, "desktop_opened")
    cmd = ["open", url]
    code, out = ab(root, paths, args, cmd)
    success_or_raise(code, out)
    wait_until = str(args.get("wait_until") or "networkidle")
    wait_code, wait_out = ab(root, paths, args, ["wait", "--load", wait_until])
    if wait_code != 0:
        out = f"{out}\nwait warning: {wait_out}"
    snap_cmd = ["snapshot", "-i"]
    if args.get("json", True):
        snap_cmd.append("--json")
    snap_code, snap_out = ab(root, paths, args, snap_cmd)
    meta = metadata(paths)
    output_lines = [
        "open_ok=true",
        f"url: {url}",
        f"wait_until: {wait_until}",
    ]
    if out:
        output_lines.append(f"open_result: {out}")
    if snap_code == 0:
        parsed = parse_snapshot_json(snap_out)
        if parsed is not None:
            snapshot_file = write_json_artifact(root, paths, "open-snapshot", parsed)
            refs = parsed.get("refs")
            refs_count = len(refs) if isinstance(refs, list) else 0
            output_lines.extend(
                [
                    f"title: {parsed.get('title') or '(unknown)'}",
                    f"refs_count: {refs_count}",
                    f"snapshot_file: {snapshot_file}",
                ]
            )
            if _snapshot_empty(parsed, refs_count):
                output_lines.extend(_empty_snapshot_guidance(snapshot_file))
            meta.update(
                {
                    "snapshot_file": str(snapshot_file),
                    "snapshot_title": parsed.get("title"),
                    "snapshot_refs_count": refs_count,
                }
            )
        else:
            snapshot_file = write_text_artifact(root, paths, "open-snapshot", snap_out)
            output_lines.extend(
                [
                    f"snapshot_file: {snapshot_file}",
                    f"snapshot_raw_length: {len(snap_out)}",
                ]
            )
            meta["snapshot_file"] = str(snapshot_file)
    else:
        output_lines.append(f"snapshot_warning: {snap_out}")
    return cap_output("\n".join(output_lines)), meta


def action_snapshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if _manual_desktop_same_profile(root, paths):
        return _desktop_snapshot_payload(root, paths, args, "desktop_snapshot")
    cmd = ["snapshot", "-i"]
    if args.get("json", True):
        cmd.append("--json")
    code, out = ab(root, paths, args, cmd)
    success_or_raise(code, out)
    meta = metadata(paths)
    parsed = parse_snapshot_json(out)
    if parsed is not None:
        snapshot_file = write_json_artifact(root, paths, "snapshot", parsed)
        refs = parsed.get("refs")
        refs_count = len(refs) if isinstance(refs, list) else 0
        meta.update(
            {
                "snapshot_file": str(snapshot_file),
                "snapshot_title": parsed.get("title"),
                "snapshot_refs_count": refs_count,
            }
        )
        output_lines = [
            "snapshot_ok=true",
            f"title: {parsed.get('title') or '(unknown)'}",
            f"refs_count: {refs_count}",
            f"snapshot_file: {snapshot_file}",
        ]
        if _snapshot_empty(parsed, refs_count):
            output_lines.extend(_empty_snapshot_guidance(snapshot_file))
        output = "\n".join(output_lines)
        return output, meta
    snapshot_file = write_text_artifact(root, paths, "snapshot", out)
    meta["snapshot_file"] = str(snapshot_file)
    output = "\n".join(
        [
            "snapshot_ok=true",
            f"snapshot_file: {snapshot_file}",
            f"snapshot_raw_length: {len(out)}",
        ]
    )
    return output, meta


def action_click(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    selector = str(args.get("selector") or "").strip()
    if not selector:
        raise ToolError("selector is required for click")
    if _manual_desktop_same_profile(root, paths):
        result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), _desktop_eval_click(selector))
        if not isinstance(result, dict) or not result.get("clicked"):
            reason = result.get("reason") if isinstance(result, dict) else "not_found"
            raise ToolError(f"desktop click failed: {reason}")
        time.sleep(1.0)
        output, meta = _desktop_snapshot_payload(root, paths, args, "desktop_clicked")
        return "\n".join(["desktop_click_ok=true", f"selector: {selector}", output]), meta
    code, out = ab(root, paths, args, ["click", selector])
    return success_or_raise(code, out), metadata(paths)


def action_fill(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    selector = str(args.get("selector") or "").strip()
    text = str(args.get("text") or "")
    if not selector:
        raise ToolError("selector is required for fill")
    if text == "":
        raise ToolError("text is required for fill")
    if _manual_desktop_same_profile(root, paths):
        expr = f"""
(() => {{
  const el = document.querySelector({selector!r});
  if (!el) return {{ filled: false, reason: 'not_found' }};
  el.focus();
  if ('value' in el) el.value = {text!r};
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return {{ filled: true }};
}})()
"""
        result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), expr)
        if not isinstance(result, dict) or not result.get("filled"):
            reason = result.get("reason") if isinstance(result, dict) else "unknown"
            raise ToolError(f"desktop fill failed: {reason}")
        output, meta = _desktop_snapshot_payload(root, paths, args, "desktop_filled")
        return "\n".join(["desktop_fill_ok=true", f"selector: {selector}", output]), meta
    code, out = ab(root, paths, args, ["fill", selector, text])
    return success_or_raise(code, out), metadata(paths)


def action_wait(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if _manual_desktop_same_profile(root, paths):
        wait_spec, aux = _desktop_eval_wait(args)
        if wait_spec == "sleep":
            time.sleep(aux)
            meta = metadata(paths)
            meta["manual_desktop_active"] = True
            return f"desktop_wait_ok=true\nslept_seconds: {aux:.1f}", meta
        spec = json.loads(wait_spec)
        deadline = float(spec["deadline"])
        while True:
            value = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), spec["expr"])
            if spec["kind"] == "load" and str(value) in {"interactive", "complete", spec["needle"]}:
                break
            if spec["kind"] == "url" and spec["needle"] in str(value):
                break
            if spec["kind"] == "text" and spec["needle"] in str(value):
                break
            if spec["kind"] == "selector" and bool(value):
                break
            if time.time() >= deadline:
                raise ToolError(f"desktop wait timed out for {spec['kind']}={spec['needle']}")
            time.sleep(aux)
        meta = metadata(paths)
        meta["manual_desktop_active"] = True
        return f"desktop_wait_ok=true\nwait_kind: {spec['kind']}\nwait_value: {spec['needle']}", meta
    if args.get("wait_until"):
        cmd = ["wait", "--load", str(args["wait_until"])]
    elif args.get("text"):
        cmd = ["wait", "--text", str(args["text"])]
    elif args.get("url"):
        cmd = ["wait", "--url", str(args["url"])]
    elif args.get("selector"):
        cmd = ["wait", str(args["selector"])]
    else:
        cmd = ["wait", "1000"]
    code, out = ab(root, paths, args, cmd)
    return success_or_raise(code, out), metadata(paths)


def action_screenshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = screenshot_path(root, paths, args)
    code, out = ab(root, paths, args, ["screenshot", str(target)])
    success_or_raise(code, out)
    meta = metadata(paths)
    meta["screenshot"] = str(target)
    return f"screenshot saved: {target}", meta
