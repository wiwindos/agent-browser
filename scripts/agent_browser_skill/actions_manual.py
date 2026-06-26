from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.actions_generic import action_open
from agent_browser_skill.browser import cdp, dashboard, desktop
from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.core.artifacts import artifact_download_files
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.core.paths import ensure_inside, remember_url, remembered_url
from agent_browser_skill.core.snapshot_artifacts import compact_excerpt, write_json_artifact, write_text_artifact
from agent_browser_skill.core.workflow import build_browser_workflow
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime import dependencies as runtime_deps
from agent_browser_skill.runtime import process as process_runtime


def _state_artifacts(root: Path, paths: dict[str, Path], prefix: str, state: dict[str, Any]) -> tuple[Path, Path]:
    state_file = write_json_artifact(root, paths, prefix, state)
    text_file = write_text_artifact(root, paths, f"{prefix}-text", str(state.get("text") or ""))
    return state_file, text_file


def _state_summary_lines(prefix: str, state: dict[str, Any], state_file: Path, text_file: Path, challenge: bool) -> list[str]:
    return [
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


def _browser_state_output(prefix: str, state: dict[str, Any], state_file: Path, text_file: Path, challenge: bool) -> str:
    return "\n".join(_state_summary_lines(prefix, state, state_file, text_file, challenge))


def _artifact_excerpt(path: Path, max_chars: int, mode: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    if mode == "tail":
        return "..." + text[-max_chars:]
    return text[:max_chars] + "..."


def action_challenge_detected(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    handoff = str(args.get("handoff") or "manual_desktop").strip().lower()
    manual_handoff = handoff in {"manual_desktop", "desktop", "novnc", "vnc"}

    snapshot = ""
    detected = False
    screenshot = None
    reusable_manual_access = False
    if url and manual_handoff:
        if desktop.manual_desktop_running(root):
            remember_url(root, paths, url)
            desktop.desktop_navigate(args, url)
            time.sleep(2.0)
            state = desktop.desktop_page_state(args)
            snapshot = desktop.state_snapshot(state)
            detected = desktop.snapshot_needs_manual_action(snapshot)
            url = str(state.get("url") or url)
            reusable_manual_access = desktop.manual_access_running(root)
    elif url:
        open_args = dict(args)
        open_args.setdefault("wait_until", "domcontentloaded")
        action_open(root, paths, open_args)

    if not manual_handoff and not snapshot:
        snapshot = desktop.current_snapshot(root, paths, args)
        detected = desktop.snapshot_needs_manual_action(snapshot)
        screenshot = desktop.save_challenge_screenshot(root, paths, args) if detected or args.get("screenshot", True) else None
    dash_code = 0
    dash_out = ""
    dash_port = dashboard.dashboard_port_from(args)
    dash_url = dashboard.dashboard_url(args, dash_port)
    if manual_handoff:
        try:
            if reusable_manual_access:
                dash_url = dashboard.novnc_url(args, dash_port)
                vnc_password = desktop.manual_access_password(root)
                dash_out = "\n".join(
                    [
                        "manual_desktop_started=true",
                        "manual_desktop_reused=true",
                        f"manual_desktop_url: {dash_url}",
                        f"vnc_passcode: {vnc_password}",
                    ]
                )
            else:
                desktop_out, desktop_meta = action_manual_desktop(root, paths, args)
                dash_url = desktop_meta.get("manual_desktop_url") or desktop_meta.get("dashboard_url") or dash_url
                dash_port = int(desktop_meta.get("dashboard_port") or dash_port)
                dash_out = desktop_out
            try:
                live_check_seconds = max(1.0, min(float(args.get("live_check_seconds") or 10), 30.0))
                live_state, live_detected = desktop.wait_for_clear_desktop_page(args, live_check_seconds)
                live_snapshot = desktop.state_snapshot(live_state)
                snapshot = live_snapshot
                detected = bool(live_detected)
                url = str(live_state.get("url") or url)

                if desktop.state_has_usable_page(live_state) and not live_detected:
                    state_file, text_file = _state_artifacts(root, paths, "challenge-live-state", live_state)
                    checkpoint = desktop.write_challenge_checkpoint(
                        paths,
                        url=str(live_state.get("url") or url),
                        snapshot=live_snapshot,
                        screenshot=None,
                        detected=False,
                    )
                    access_note = process_runtime.stop_manual_access(root)
                    meta = metadata(paths)
                    meta.update(
                        {
                            "challenge_detected": False,
                            "manual_desktop_already_clear": True,
                            "manual_desktop_active": True,
                            "manual_access_closed": True,
                            "checkpoint": str(checkpoint),
                            "dashboard_port": dash_port,
                            "dashboard_url": dash_url,
                            "current_url": live_state.get("url"),
                            "title": live_state.get("title"),
                            "state_file": str(state_file),
                            "text_file": str(text_file),
                        }
                    )
                    meta.update(
                        build_browser_workflow(
                            state="page_ready",
                            user_action_required=False,
                            recommended_next_action="desktop_snapshot",
                            recommended_next_args={"profile": paths["site"].name},
                            next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
                            user_message_hint="The browser page is already usable. Continue with the suggested browser action and do not wait for the user.",
                        )
                    )
                    output = "\n".join(
                        [
                            "challenge_detected=false",
                            "manual_desktop_already_clear=true",
                            "The live noVNC/manual desktop page is already past the challenge.",
                            "Do not ask the user to solve a captcha. Continue this task with action=desktop_snapshot, action=desktop_open, or action=desktop_screenshot using the same site_key/profile.",
                            "Public noVNC/VNC access is now closed. Chrome stays alive internally for CDP actions.",
                            f"current_url: {live_state.get('url')}",
                            f"title: {live_state.get('title')}",
                            f"manual_access: {access_note}",
                            f"checkpoint: {checkpoint}",
                            f"state_file: {state_file}",
                            f"text_file: {text_file}",
                            f"text_excerpt: {compact_excerpt(live_state.get('text') or '', 500)}",
                        ]
                    )
                    return output, meta
                dash_out = "\n".join(
                    part
                    for part in (
                        dash_out,
                        f"live_desktop_check: challenge_detected={str(live_detected).lower()} url={live_state.get('url')} after={live_check_seconds:.0f}s",
                    )
                    if part
                )
            except ToolError as exc:
                dash_out = "\n".join(part for part in (dash_out, f"live_desktop_check_failed: {exc}") if part)
        except ToolError as exc:
            dash_code = 1
            dash_out = f"manual_desktop failed: {exc}"
    else:
        dash_code, dash_out, dash_port, dash_url = dashboard.start_dashboard(root, args)
    checkpoint = desktop.write_challenge_checkpoint(
        paths,
        url=url,
        snapshot=snapshot,
        screenshot=screenshot,
        detected=detected,
    )

    meta = metadata(paths)
    meta.update(
        {
            "challenge_detected": detected,
            "checkpoint": str(checkpoint),
            "screenshot": str(screenshot) if screenshot else None,
            "dashboard_port": dash_port,
            "dashboard_url": dash_url,
        }
    )
    continue_args = {"profile": paths["site"].name}
    if url:
        continue_args["url"] = url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if detected else "page_ready",
            user_action_required=bool(detected),
            recommended_next_action="continue_after_manual" if detected else "desktop_snapshot",
            recommended_next_args=continue_args if detected else {"profile": paths["site"].name},
            next_tool_call={"action": "continue_after_manual", **continue_args}
            if detected
            else {"action": "desktop_snapshot", "profile": paths["site"].name},
            external_urls={"dashboard_url": dash_url} if dash_url else None,
            user_message_hint=(
                "Wait for the user only if the page still needs manual interaction."
                if detected
                else "No challenge was detected. Continue with browser actions instead of asking the user to confirm."
            ),
        )
    )

    if detected:
        output = "\n".join(
            [
                "challenge_detected=true",
                "Manual action required.",
                "Ask the user to complete the Cloudflare/captcha/login check in the current browser session, then wait for any completion confirmation message.",
                "Do not try to bypass the challenge automatically.",
                f"dashboard_url: {dash_url}",
                f"handoff: {handoff}",
                f"dashboard_status: {'started' if dash_code == 0 else 'start_failed'}",
                f"dashboard_output: {dash_out}",
                f"profile: {paths['profile']}",
                f"checkpoint: {checkpoint}",
                f"screenshot: {screenshot or '(not saved)'}",
                "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual with the same site_key/url.",
                "",
                "After the user's next confirmation message, immediately call action=continue_after_manual with the same site_key/url. Do not require an exact trigger word and do not rediscover tools first.",
            ]
        )
    else:
        output = "\n".join(
            [
                "challenge_detected=false",
                "No known Cloudflare/captcha challenge text was detected in the current snapshot.",
                f"dashboard_url: {dash_url}",
                f"dashboard_status: {'started' if dash_code == 0 else 'start_failed'}",
                f"checkpoint: {checkpoint}",
            ]
        )
    return output, meta


def action_continue_after_manual(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    if desktop.manual_desktop_running(root):
        try:
            state = desktop.desktop_page_state(args)
            snapshot = desktop.state_snapshot(state)
            still_detected = desktop.snapshot_needs_manual_action(snapshot)
            checkpoint = desktop.write_challenge_checkpoint(
                paths,
                url=str(state.get("url") or url),
                snapshot=snapshot,
                screenshot=None,
                detected=still_detected,
            )
            meta = metadata(paths)
            meta.update(
                {
                    "challenge_detected": still_detected,
                    "checkpoint": str(checkpoint),
                    "manual_desktop_active": True,
                    "current_url": state.get("url"),
                    "title": state.get("title"),
                }
            )
            next_args = {"profile": paths["site"].name}
            current_url = str(state.get("url") or url or "").strip()
            if current_url:
                next_args["url"] = current_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if still_detected else "page_ready",
                    user_action_required=bool(still_detected),
                    recommended_next_action="continue_after_manual" if still_detected else "desktop_snapshot",
                    recommended_next_args=next_args if still_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **next_args}
                    if still_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    user_message_hint=(
                        "The page still needs manual interaction in the existing browser session."
                        if still_detected
                        else "The page is already usable. Continue with browser automation and do not re-open manual access."
                    ),
                )
            )
            if not still_detected and str(state.get("url") or "") != "about:blank":
                state_file, text_file = _state_artifacts(root, paths, "continue-after-manual-state", state)
                access_note = process_runtime.stop_manual_access(root)
                output = "\n".join(
                    [
                        "challenge_cleared=true",
                        "Manual desktop page is already past the challenge.",
                        "Public noVNC/VNC access is now closed. Chrome stays alive internally for agent CDP actions.",
                        "For the next browser steps use action=desktop_snapshot, action=desktop_open, or action=desktop_screenshot with the same site_key/url.",
                        f"current_url: {state.get('url')}",
                        f"title: {state.get('title')}",
                        f"profile: {paths['profile']}",
                        f"manual_access: {access_note}",
                        f"checkpoint: {checkpoint}",
                        f"state_file: {state_file}",
                        f"text_file: {text_file}",
                        f"text_excerpt: {compact_excerpt(state.get('text') or '', 500)}",
                    ]
                )
                meta["manual_access_closed"] = True
                meta["state_file"] = str(state_file)
                meta["text_file"] = str(text_file)
                return output, meta
            output = "\n".join(
                [
                    "challenge_cleared=false",
                    "The live manual desktop still appears to show a challenge/login page.",
                    "Ask the user to finish it in the already-open noVNC window and wait for any completion confirmation message.",
                    "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual.",
                    f"current_url: {state.get('url')}",
                    f"title: {state.get('title')}",
                    f"checkpoint: {checkpoint}",
                ]
            )
            return output, meta
        except ToolError:
            pass

    stop_note = process_runtime.stop_manual_desktop(root)
    stale_locks = process_runtime.wait_profile_unlocked(paths["profile"], timeout=5.0)
    removed_after_stop = []
    if stale_locks:
        removed_after_stop = process_runtime.unlock_profile(paths["profile"])

    if url:
        open_args = dict(args)
        open_args.setdefault("wait_until", "domcontentloaded")
        action_open(root, paths, open_args)

    snapshot = desktop.current_snapshot(root, paths, args)
    still_detected = desktop.snapshot_needs_manual_action(snapshot)
    screenshot = desktop.save_challenge_screenshot(root, paths, {**args, "filename": "after-manual.png"})
    checkpoint = desktop.write_challenge_checkpoint(
        paths,
        url=url,
        snapshot=snapshot,
        screenshot=screenshot,
        detected=still_detected,
    )

    meta = metadata(paths)
    meta.update(
        {
            "challenge_detected": still_detected,
            "checkpoint": str(checkpoint),
            "screenshot": str(screenshot) if screenshot else None,
        }
    )
    next_args = {"profile": paths["site"].name}
    if url:
        next_args["url"] = url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if still_detected else "session_resumable",
            user_action_required=bool(still_detected),
            recommended_next_action="continue_after_manual" if still_detected else "desktop_snapshot",
            recommended_next_args=next_args if still_detected else {"profile": paths["site"].name},
            next_tool_call={"action": "continue_after_manual", **next_args}
            if still_detected
            else {"action": "desktop_snapshot", "profile": paths["site"].name},
            user_message_hint=(
                "The manual check is not done yet. Wait for the user to finish it."
                if still_detected
                else "Manual access can stay closed. Continue with browser automation using the preserved session."
            ),
        )
    )
    if still_detected:
        output = "\n".join(
            [
                "challenge_cleared=false",
                "The challenge/login page is still visible.",
                "Ask the user to finish the manual check and wait for any completion confirmation message.",
                "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual.",
                f"manual_desktop_stop: {stop_note}",
                f"removed_stale_locks_after_stop: {len(removed_after_stop)}",
                f"checkpoint: {checkpoint}",
                f"screenshot: {screenshot or '(not saved)'}",
            ]
        )
    else:
        snapshot_file = write_text_artifact(root, paths, "continue-after-manual-snapshot", snapshot)
        output = "\n".join(
            [
                "challenge_cleared=true",
                "Manual check appears complete. The current profile/session is preserved and can be reused.",
                f"profile: {paths['profile']}",
                f"manual_desktop_stop: {stop_note}",
                f"removed_stale_locks_after_stop: {len(removed_after_stop)}",
                f"checkpoint: {checkpoint}",
                f"snapshot_file: {snapshot_file}",
                f"snapshot_excerpt: {compact_excerpt(snapshot, 500)}",
            ]
        )
        meta["snapshot_file"] = str(snapshot_file)
    return output, meta


def action_share_session(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    code, out, port, url = dashboard.start_dashboard(root, args)
    meta = metadata(paths)
    meta.update({"dashboard_port": port, "dashboard_url": url})
    if code != 0:
        raise ToolError(f"failed to start dashboard on port {port}: {out}")
    output = "\n".join(
        [
            "dashboard_started=true",
            f"dashboard_url: {url}",
            f"dashboard_port: {port}",
            "Send this URL to the user so they can complete the manual browser challenge.",
            "next_step: after the user's next completion confirmation message, call continue_after_manual with the same site_key/url.",
            "After the user's next confirmation message, call continue_after_manual with the same site_key/url. Do not require an exact trigger word.",
            out,
        ]
    )
    return output, meta


def action_manual_desktop(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout = timeout_from(args)
    url = str(args.get("url") or "").strip()
    if "/vnc.html" in url or "/vnc_auto.html" in url or "/vnc_lite.html" in url:
        url = remembered_url(root, paths)
    if not url:
        url = remembered_url(root, paths)
    if not url:
        if desktop.manual_desktop_running(root):
            public_port = dashboard.dashboard_port_from(args)
            state = desktop.desktop_page_state(args)
            url_out = dashboard.novnc_url(args, public_port)
            vnc_password = desktop.manual_access_password(root)
            meta = metadata(paths)
            meta.update(
                {
                    "manual_desktop_url": url_out,
                    "dashboard_url": url_out,
                    "dashboard_port": public_port,
                    "manual_access_password_required": True,
                    "vnc_passcode": vnc_password,
                    "manual_desktop_active": True,
                    "current_url": state.get("url"),
                    "title": state.get("title"),
                }
            )
            challenge_detected = desktop.state_needs_manual_action(state)
            continue_args = {"profile": paths["site"].name}
            current_url = str(state.get("url") or "").strip()
            if current_url:
                continue_args["url"] = current_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if challenge_detected else "page_ready",
                    user_action_required=bool(challenge_detected),
                    recommended_next_action="continue_after_manual" if challenge_detected else "desktop_snapshot",
                    recommended_next_args=continue_args if challenge_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **continue_args}
                    if challenge_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                    credentials_to_show_user={"vnc_passcode": vnc_password},
                    user_message_hint=(
                        "Use the existing manual browser window only if the page still needs user input."
                        if challenge_detected
                        else "The page is already usable. Continue with browser automation and do not ask the user to solve a challenge."
                    ),
                )
            )
            output = "\n".join(
                [
                    "manual_desktop_started=true",
                    "manual_desktop_reused=true",
                    f"manual_desktop_url: {url_out}",
                    f"vnc_passcode: {vnc_password}",
                    f"current_url: {state.get('url')}",
                    f"title: {state.get('title')}",
                    f"next_step: {'wait for the user and then call continue_after_manual' if challenge_detected else 'continue with action=desktop_snapshot or action=desktop_open using the same profile'}",
                    "The live manual desktop is already running. Continue with desktop_snapshot/desktop_open.",
                ]
            )
            return output, meta
        raise ToolError("url is required for manual_desktop")
    remember_url(root, paths, url)

    public_port = dashboard.dashboard_port_from(args)
    vnc_port = int(args.get("vnc_port") or 5900)
    cdp_port = desktop.desktop_cdp_port_from(args)
    vnc_password = desktop.manual_access_password(root, reset=True)
    display = str(args.get("display") or ":99")
    width = int(args.get("width") or 1365)
    height = int(args.get("height") or 900)

    runtime_deps.close_agent_browser(root, timeout)
    dashboard.stop_dashboard_proxy(root, public_port)
    dashboard.dashboard_command(root, args, "stop", dashboard.dashboard_internal_port_from(args))
    process_runtime.stop_manual_desktop(root)
    process_runtime.unlock_profile(paths["profile"])

    notes = [
        runtime_deps.install_browser_dependencies(root, timeout, args),
        runtime_deps.install_desktop_dependencies(root, timeout),
    ]

    d = desktop.desktop_dir(root)
    chrome = desktop.find_chrome_binary(root)
    desktop.configure_chrome_downloads(paths["profile"], paths["downloads"])
    env = {
        "DISPLAY": display,
        "LANG": "ru_RU.UTF-8",
        "LC_ALL": "C.UTF-8",
    }

    process_runtime.start_bg(
        root,
        d / "xvfb.pid",
        d / "xvfb.log",
        ["Xvfb", display, "-screen", "0", f"{width}x{height}x24", "-nolisten", "tcp", "-ac"],
        env,
    )
    process_runtime.start_bg(root, d / "openbox.pid", d / "openbox.log", ["openbox"], env)
    process_runtime.start_bg(
        root,
        d / "x11vnc.pid",
        d / "x11vnc.log",
        [
            "x11vnc",
            "-display",
            display,
            "-forever",
            "-shared",
            "-passwdfile",
            str(desktop.desktop_dir(root) / "vnc.pass"),
            "-listen",
            "127.0.0.1",
            "-rfbport",
            str(vnc_port),
        ],
        env,
    )
    process_runtime.start_bg(
        root,
        d / "chrome.pid",
        d / "chrome.log",
        [
            chrome,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-features=Translate,BackForwardCache",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={paths['profile']}",
            f"--window-size={width},{height}",
            "--lang=ru-RU",
            "--start-maximized",
            url,
        ],
        env,
    )
    web_dir = "/usr/share/novnc"
    if not Path(web_dir).exists():
        web_dir = "/usr/share/novnc/html"
    process_runtime.start_bg(
        root,
        d / "websockify.pid",
        d / "websockify.log",
        [
            "websockify",
            "--web",
            web_dir,
            f"0.0.0.0:{public_port}",
            f"127.0.0.1:{vnc_port}",
        ],
        env,
    )

    url_out = dashboard.novnc_url(args, public_port)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_url": url_out,
            "dashboard_url": url_out,
            "dashboard_port": public_port,
            "vnc_port": vnc_port,
            "desktop_cdp_port": cdp_port,
            "manual_access_password_required": True,
            "display": display,
        }
    )

    live_check_seconds = max(0.0, min(float(args.get("live_check_seconds") or 6), 30.0))
    if live_check_seconds > 0:
        try:
            live_state, live_detected = desktop.wait_for_clear_desktop_page(args, live_check_seconds)
            if desktop.state_has_usable_page(live_state) and not live_detected:
                state_file, text_file = _state_artifacts(root, paths, "manual-desktop-live-state", live_state)
                meta.update(
                    {
                        "manual_desktop_active": True,
                        "manual_desktop_already_clear": True,
                        "challenge_detected": False,
                        "manual_access_closed": False,
                        "current_url": live_state.get("url"),
                        "title": live_state.get("title"),
                        "manual_desktop_url": url_out,
                        "dashboard_url": url_out,
                        "dashboard_port": public_port,
                        "vnc_port": vnc_port,
                        "vnc_passcode": vnc_password,
                        "manual_access_password_required": True,
                        "state_file": str(state_file),
                        "text_file": str(text_file),
                    }
                )
                meta.update(
                    build_browser_workflow(
                        state="page_ready",
                        user_action_required=False,
                        recommended_next_action="desktop_snapshot",
                        recommended_next_args={"profile": paths["site"].name},
                        next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
                        external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                        credentials_to_show_user={"vnc_passcode": vnc_password},
                        user_message_hint="The browser page is already usable. Continue with browser automation and do not wait for the user.",
                    )
                )
                output = "\n".join(
                    [
                        "manual_desktop_started=true",
                        "manual_desktop_already_clear=true",
                        "challenge_detected=false",
                        "The live manual desktop page is already usable. Do not ask the user to solve a captcha or login unless a later snapshot shows a challenge.",
                        "Classic noVNC/VNC access remains open because manual_desktop was requested directly.",
                        f"manual_desktop_url: {url_out}",
                        f"public_port: {public_port}",
                        f"vnc_port: {vnc_port}",
                        f"vnc_passcode: {vnc_password}",
                        f"current_url: {live_state.get('url')}",
                        f"title: {live_state.get('title')}",
                        f"desktop_cdp_port: {cdp_port}",
                        f"profile: {paths['profile']}",
                        f"state_file: {state_file}",
                        f"text_file: {text_file}",
                        f"text_excerpt: {compact_excerpt(live_state.get('text') or '', 500)}",
                        *[f"bootstrap: {note}" for note in notes],
                    ]
                )
                return output, meta
            meta.update(
                {
                    "manual_desktop_active": True,
                    "challenge_detected": bool(live_detected),
                    "current_url": live_state.get("url"),
                    "title": live_state.get("title"),
                }
            )
            next_args = {"profile": paths["site"].name}
            live_url = str(live_state.get("url") or url or "").strip()
            if live_url:
                next_args["url"] = live_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if live_detected else "page_ready",
                    user_action_required=bool(live_detected),
                    recommended_next_action="continue_after_manual" if live_detected else "desktop_snapshot",
                    recommended_next_args=next_args if live_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **next_args}
                    if live_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                    credentials_to_show_user={"vnc_passcode": vnc_password},
                    user_message_hint=(
                        "Wait for the user only if the live page still needs manual interaction."
                        if live_detected
                        else "The live page is already usable. Continue automatically."
                    ),
                )
            )
        except ToolError as exc:
            meta["live_desktop_check_error"] = str(exc)

    if "workflow_state" not in meta:
        meta.update(
            build_browser_workflow(
                state="awaiting_user_completion",
                user_action_required=True,
                recommended_next_action="continue_after_manual",
                recommended_next_args={"profile": paths["site"].name, "url": url},
                next_tool_call={"action": "continue_after_manual", "profile": paths["site"].name, "url": url},
                external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                credentials_to_show_user={"vnc_passcode": vnc_password},
                user_message_hint="The user must use the manual browser session if the page still shows a login, captcha, or challenge.",
            )
        )

    output = "\n".join(
        [
            "manual_desktop_started=true",
            f"manual_desktop_url: {url_out}",
            f"public_port: {public_port}",
            f"vnc_port: {vnc_port}",
            f"desktop_cdp_port: {cdp_port}",
            f"vnc_passcode: {vnc_password}",
            f"display: {display}",
            f"profile: {paths['profile']}",
            "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual with the same profile/url if the page still needs manual interaction.",
            "Open the URL, complete the Cloudflare/captcha/login check in the real server-side Chrome window, then wait for the user's next completion confirmation message. Do not require an exact trigger word.",
            *[f"bootstrap: {note}" for note in notes],
        ]
    )
    return output, meta


def action_stop_desktop(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    output = process_runtime.stop_manual_desktop(root)
    return output, metadata(paths)


def action_close_manual_access(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    output = process_runtime.stop_manual_access(root)
    meta = metadata(paths)
    meta["manual_access_closed"] = True
    meta.update(
        build_browser_workflow(
            state="session_resumable",
            user_action_required=False,
            recommended_next_action="desktop_snapshot",
            recommended_next_args={"profile": paths["site"].name},
            next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
        )
    )
    return output, meta


def action_desktop_open(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    if not url:
        raise ToolError("url is required for desktop_open")
    if not desktop.manual_desktop_running(root):
        output, meta = action_manual_desktop(root, paths, args)
        meta["desktop_open_started_manual_desktop"] = True
        return "\n".join(["desktop_open_started_manual_desktop=true", output]), meta
    remember_url(root, paths, url)
    desktop.desktop_navigate(args, url)
    time.sleep(2.0)
    state = desktop.desktop_page_state(args)
    state_file, text_file = _state_artifacts(root, paths, "desktop-open-state", state)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    challenge_detected = desktop.state_needs_manual_action(state)
    continue_args = {"profile": paths["site"].name}
    current_url = str(state.get("url") or url).strip()
    if current_url:
        continue_args["url"] = current_url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if challenge_detected else "page_ready",
            user_action_required=bool(challenge_detected),
            recommended_next_action="continue_after_manual" if challenge_detected else "desktop_snapshot",
            recommended_next_args=continue_args if challenge_detected else {"profile": paths["site"].name},
            next_tool_call={"action": "continue_after_manual", **continue_args}
            if challenge_detected
            else {"action": "desktop_snapshot", "profile": paths["site"].name},
            user_message_hint=(
                "Only wait for the user if the newly opened page still needs manual interaction."
                if challenge_detected
                else "The page is already usable. Continue with browser actions."
            ),
        )
    )
    output = "\n".join(
        _state_summary_lines("desktop_opened", state, state_file, text_file, challenge_detected)
        + [
            f"next_step: {'wait for the user and then call continue_after_manual' if challenge_detected else 'continue with action=desktop_snapshot or action=saby_tenders_csv as needed'}",
        ]
    )
    return output, meta


def action_desktop_snapshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    state = desktop.desktop_page_state(args)
    challenge = desktop.state_needs_manual_action(state)
    state_file, text_file = _state_artifacts(root, paths, "desktop-snapshot-state", state)
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
    output = "\n".join(_state_summary_lines("desktop_snapshot", state, state_file, text_file, challenge))
    return output, meta


def action_desktop_screenshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    target = desktop.screenshot_path(root, paths, args)
    result = cdp.cdp_call(desktop.desktop_cdp_port_from(args), "Page.captureScreenshot", {"format": "png", "fromSurface": True})
    data = result.get("data")
    if not isinstance(data, str) or not data:
        raise ToolError("manual desktop screenshot returned no image data")
    target.write_bytes(base64.b64decode(data))
    meta = metadata(paths)
    meta.update({"manual_desktop_active": True, "screenshot": str(target)})
    return f"desktop screenshot saved: {target}", meta


def action_read_artifact(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise ToolError("path is required for read_artifact")
    target = ensure_inside(Path(raw_path), root)
    browser_artifacts_root = ensure_inside(root / "browser-artifacts", root)
    if browser_artifacts_root not in target.parents and target != browser_artifacts_root:
        raise ToolError("read_artifact only allows files inside browser-artifacts")
    if not target.exists():
        raise ToolError(f"artifact file not found: {target}")
    if not target.is_file():
        raise ToolError("read_artifact requires a file path, not a directory")
    max_chars = max(100, min(int(args.get("max_chars") or 1200), 3000))
    mode = str(args.get("mode") or "head").strip().lower()
    if mode not in {"head", "tail"}:
        mode = "head"
    excerpt = _artifact_excerpt(target, max_chars, mode)
    meta = metadata(paths)
    meta.update(
        {
            "artifact_file": str(target),
            "artifact_size_bytes": target.stat().st_size,
            "artifact_mode": mode,
            "artifact_excerpt_chars": len(excerpt),
        }
    )
    output = "\n".join(
        [
            "artifact_read_ok=true",
            f"artifact_file: {target}",
            f"artifact_mode: {mode}",
            f"artifact_size_bytes: {target.stat().st_size}",
            f"artifact_excerpt_chars: {len(excerpt)}",
            "",
            cap_output(excerpt, 12000),
        ]
    )
    return output, meta


def action_navigate_pagination(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    target = str(args.get("target") or "last").strip().lower()
    if target not in {"first", "prev", "next", "last"}:
        raise ToolError("target must be one of: first, prev, next, last")
    script = f"""
(() => {{
  const target = {json.dumps(target)};
  const anchors = Array.from(document.querySelectorAll('a[href]')).map((a) => {{
    const text = (a.textContent || '').replace(/\\s+/g, ' ').trim();
    const rel = (a.getAttribute('rel') || '').toLowerCase();
    const aria = (a.getAttribute('aria-label') || '').toLowerCase();
    return {{
      href: a.href,
      text,
      rel,
      aria,
      page: /^\\d+$/.test(text) ? Number(text) : null,
    }};
  }});
  const choose = (...predicates) => anchors.find((a) => predicates.some((p) => p(a)));
  const byRel = {{
    first: choose((a) => a.rel.includes('first')),
    prev: choose((a) => a.rel.includes('prev')),
    next: choose((a) => a.rel.includes('next')),
    last: choose((a) => a.rel.includes('last')),
  }};
  const byLabel = {{
    first: choose((a) => /first|начал|первая/.test(a.aria), (a) => /^(«|<<|first|первая)$/i.test(a.text)),
    prev: choose((a) => /prev|previous|назад/.test(a.aria), (a) => /^(‹|<|«|prev|previous|назад)$/i.test(a.text)),
    next: choose((a) => /next|след/.test(a.aria), (a) => /^(›|>|»|next|след)$/i.test(a.text)),
    last: choose((a) => /last|конец|послед/.test(a.aria), (a) => /^(»|>>|last|последняя|конец)$/i.test(a.text)),
  }};
  const numbered = anchors.filter((a) => a.page !== null);
  const byNumber = {{
    first: numbered.sort((a, b) => a.page - b.page)[0] || null,
    last: numbered.sort((a, b) => b.page - a.page)[0] || null,
  }};
  const match = byRel[target] || byLabel[target] || byNumber[target] || null;
  return {{
    target,
    href: match ? match.href : null,
    text: match ? match.text : null,
    rel: match ? match.rel : null,
    reason: byRel[target] ? 'rel' : byLabel[target] ? 'label' : byNumber[target] ? 'number' : 'none',
    numbered_pages: numbered.slice(0, 20).map((a) => a.page),
  }};
}})()
"""
    info = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    if not isinstance(info, dict) or not info.get("href"):
        raise ToolError(f"no pagination link found for target={target}")
    href = str(info["href"])
    remember_url(root, paths, href)
    desktop.desktop_navigate(args, href)
    time.sleep(1.5)
    state = desktop.desktop_page_state(args)
    challenge = desktop.state_needs_manual_action(state)
    state_file, text_file = _state_artifacts(root, paths, f"pagination-{target}-state", state)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "challenge_detected": challenge,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "pagination_target": target,
            "pagination_match": info,
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    output = "\n".join(
        [
            f"navigate_pagination_ok=true",
            f"pagination_target: {target}",
            f"pagination_reason: {info.get('reason')}",
            f"pagination_text: {info.get('text')}",
            *_state_summary_lines("desktop_snapshot", state, state_file, text_file, challenge),
        ]
    )
    return output, meta


def action_evaluate(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    script = str(args.get("script") or args.get("code") or args.get("text") or "").strip()
    if not script:
        raise ToolError("script is required for evaluate")
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call login/manual_desktop first, then evaluate")
    before_downloads = set(paths["downloads"].glob("*")) if paths["downloads"].exists() else set()
    value = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    time.sleep(1.0)
    after_downloads = set(paths["downloads"].glob("*")) if paths["downloads"].exists() else set()
    new_downloads = sorted(after_downloads - before_downloads, key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if isinstance(value, (dict, list)):
        result_text = json.dumps(value, ensure_ascii=False, indent=2)
    elif value is None:
        result_text = "undefined/null"
    else:
        result_text = str(value)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "result_preview": compact_excerpt(result_text, 400),
            "downloads": [str(p) for p in new_downloads],
        }
    )
    result_file = write_text_artifact(root, paths, "evaluate-result", result_text)
    lines = [
        "evaluate_ok=true",
        f"profile: {paths['profile']}",
        f"downloads_dir: {paths['downloads']}",
        f"result_file: {result_file}",
        f"result_length: {len(result_text)}",
        f"result_excerpt: {compact_excerpt(result_text, 800)}",
    ]
    if new_downloads:
        lines.append("new_downloads:")
        lines.extend(str(p) for p in new_downloads)
    meta["result_file"] = str(result_file)
    meta["result_length"] = len(result_text)
    return "\n".join(lines), meta

def action_downloads(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    pattern = str(args.get("pattern") or args.get("filename") or "*.csv").strip() or "*.csv"
    timeout = timeout_from(args)
    deadline = time.time() + min(timeout, 30)
    files = artifact_download_files(root, paths["site"].name, pattern)
    while not files and time.time() < deadline:
        time.sleep(0.5)
        files = artifact_download_files(root, paths["site"].name, pattern)
    meta = metadata(paths)
    meta.update({"downloads": [str(p) for p in files], "pattern": pattern})
    if not files:
        return f"downloads_found=0\npattern: {pattern}\nsite: {paths['site'].name}", meta
    lines = [
        f"downloads_found={len(files)}",
        f"pattern: {pattern}",
        f"site: {paths['site'].name}",
        "files:",
    ]
    for p in files[:20]:
        size = p.stat().st_size if p.exists() else 0
        lines.append(f"{p} ({size} bytes)")
    return "\n".join(lines), meta

