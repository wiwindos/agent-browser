from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.actions_manual import action_manual_desktop
from agent_browser_skill.browser import cdp, desktop
from agent_browser_skill.core.args import bool_arg, timeout_from
from agent_browser_skill.core.config import MAX_TIMEOUT
from agent_browser_skill.core.helpers import safe_slug
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.core.paths import ensure_inside, remember_url, remembered_url
from agent_browser_skill.core.workflow import build_browser_workflow
from agent_browser_skill.domains.saby import (
    build_prepared_state,
    build_saby_metadata,
    build_saby_options,
    collector_script_text,
    csv_text_for_items,
    json_line,
    summarize_steps,
)
from agent_browser_skill.errors import ToolError
from agent_browser_skill.version import SKILL_VERSION


def _saby_trace_path(paths: dict[str, Path]) -> Path:
    return ensure_inside(paths["logs"] / "saby_tenders_trace.jsonl", paths["artifact"].parents[2])


def _append_saby_trace(trace_path: Path, event: str, **payload: Any) -> None:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        **payload,
    }
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def action_saby_tenders_csv(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout_args = dict(args)
    timeout_args.setdefault("timeout", MAX_TIMEOUT)
    eval_timeout = timeout_from(timeout_args)
    started_at = time.time()
    overall_deadline = started_at + max(1, eval_timeout - 2)
    prelude: list[str] = []
    requested_url = str(args.get("url") or "").strip()
    started_desktop = False
    trace_path = _saby_trace_path(paths)
    _append_saby_trace(
        trace_path,
        "action_started",
        skill_version=SKILL_VERSION,
        profile=paths["site"].name,
        requested_url=requested_url or None,
        timeout_seconds=eval_timeout,
        args={key: value for key, value in args.items() if key != "_context"},
    )

    if not desktop.manual_desktop_running(root):
        startup_url = requested_url or remembered_url(root, paths)
        if not startup_url:
            _append_saby_trace(trace_path, "startup_missing_url")
            raise ToolError("manual desktop is not running; pass url=... or call desktop_open/login/manual_desktop first, then saby_tenders_csv")
        startup_args = dict(args)
        startup_args["url"] = startup_url
        startup_args.setdefault("live_check_seconds", 4)
        _append_saby_trace(trace_path, "starting_manual_desktop", startup_url=startup_url)
        startup_output, _startup_meta = action_manual_desktop(root, paths, startup_args)
        started_desktop = True
        prelude.extend(["saby_tenders_started_manual_desktop=true", startup_output])
        _append_saby_trace(trace_path, "manual_desktop_started", startup_url=startup_url)
    elif requested_url:
        remember_url(root, paths, requested_url)
        _append_saby_trace(trace_path, "navigating_existing_manual_desktop", requested_url=requested_url)
        desktop.desktop_navigate(args, requested_url)
        time.sleep(2.0)
        _append_saby_trace(trace_path, "navigation_wait_complete", requested_url=requested_url, waited_ms=2000)

    remaining_after_start_ms = int(max(0.0, overall_deadline - time.time()) * 1000)
    collect_after_start = bool_arg(args, "collect_after_start", False)
    if started_desktop and not collect_after_start:
        prepared_state, next_tool_call = build_prepared_state(paths["site"].name, args, remaining_after_start_ms)
        filename = safe_slug(str(args.get("filename") or "saby_tenders")) + "_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
        target = ensure_inside(paths["downloads"] / filename, root)
        target.write_text(csv_text_for_items([]), encoding="utf-8-sig")
        meta = metadata(paths)
        meta.update(
            {
                "saby_tenders": prepared_state,
                "next_tool_call": next_tool_call,
                "downloads": [str(target)],
                "csv": str(target),
                "saby_trace_log": str(trace_path),
            }
        )
        meta.update(
            build_browser_workflow(
                state="session_resumable",
                user_action_required=False,
                recommended_next_action="saby_tenders_csv",
                recommended_next_args={k: v for k, v in next_tool_call.items() if k != "action"},
                next_tool_call=next_tool_call,
                user_message_hint="The browser session is ready. Continue with the suggested browser tool call instead of re-opening the desktop or rediscovering tools.",
            )
        )
        _append_saby_trace(
            trace_path,
            "prepared_for_collection",
            remaining_after_start_ms=remaining_after_start_ms,
            csv=str(target),
            next_tool_call=next_tool_call,
        )
        output = "\n".join(
            [
                f"saby_diag skill={SKILL_VERSION} complete=false prepared=true reason=manual desktop started; collection deferred",
                "saby_tenders_csv_ok=true",
                "collection_complete: false",
                "prepared_for_collection: true",
                "items_exported: 0",
                f"remaining_after_start_ms: {remaining_after_start_ms}",
                "next_action: call action=saby_tenders_csv with the same profile/mode/target_date and resume_state=true without url",
                f"next_tool_call: {json_line(next_tool_call)}",
                f"csv: {target}",
                f"trace_log: {trace_path}",
                "",
                *prelude,
            ]
        )
        return output, meta

    max_budget_for_timeout = max(100, (eval_timeout * 1000) - 1000)
    default_runtime_ms = max(100, (eval_timeout * 1000) - 8000)
    explicit_runtime = args.get("max_runtime_ms") is not None
    try:
        max_runtime_ms = int(args.get("max_runtime_ms") or default_runtime_ms)
    except (TypeError, ValueError):
        max_runtime_ms = default_runtime_ms
    max_runtime_ms = min(max(0, max_runtime_ms), max_budget_for_timeout)
    try:
        auto_resume_passes = int(args.get("auto_resume_passes", 1))
    except (TypeError, ValueError):
        auto_resume_passes = 1
    auto_resume_passes = max(0, min(auto_resume_passes, 3))
    options = build_saby_options(args, max_runtime_ms)
    _append_saby_trace(
        trace_path,
        "collector_budget_ready",
        explicit_runtime=explicit_runtime,
        max_budget_for_timeout=max_budget_for_timeout,
        default_runtime_ms=default_runtime_ms,
        max_runtime_ms=max_runtime_ms,
        auto_resume_passes=auto_resume_passes,
        options=options,
    )

    script_source = collector_script_text()
    attempts: list[dict[str, Any]] = []
    result: dict[str, Any] | None = None
    pass_index = 0

    while True:
        remaining_ms = int(max(0.0, overall_deadline - time.time()) * 1000)
        if remaining_ms < 5000:
            _append_saby_trace(
                trace_path,
                "stopping_before_pass",
                reason="remaining budget below 5000ms",
                remaining_ms=remaining_ms,
            )
            break

        run_options = dict(options)
        if pass_index > 0:
            run_options["resumeState"] = True
            run_options["resetState"] = False
        if not explicit_runtime and auto_resume_passes > 0:
            if pass_index == 0:
                run_options["maxRuntimeMs"] = min(max_runtime_ms, max(100, remaining_ms - 30000))
            else:
                run_options["maxRuntimeMs"] = min(max_runtime_ms, max(100, remaining_ms - 5000))
        run_options["maxRuntimeMs"] = min(
            max(100, int(run_options.get("maxRuntimeMs") or 100)),
            max(100, remaining_ms - 1000),
        )
        expression = (
            "window.__SABY_TENDERS_OPTIONS__ = "
            + json.dumps(run_options, ensure_ascii=False)
            + ";\n"
            + script_source
        )
        run_timeout = max(5, min(eval_timeout, int(run_options["maxRuntimeMs"] / 1000) + 8))
        pass_started_at = time.time()
        _append_saby_trace(
            trace_path,
            "pass_started",
            pass_index=pass_index + 1,
            remaining_ms=remaining_ms,
            run_timeout_seconds=run_timeout,
            run_max_runtime_ms=run_options["maxRuntimeMs"],
            resume_state=bool(run_options.get("resumeState")),
            reset_state=bool(run_options.get("resetState")),
        )
        current = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), expression, timeout=run_timeout)
        if not isinstance(current, dict):
            _append_saby_trace(trace_path, "pass_invalid_result", pass_index=pass_index + 1, result_type=type(current).__name__)
            raise ToolError("saby_tenders_csv returned an unexpected result")

        result = current
        attempt = {
            "pass": pass_index + 1,
            "complete": bool(current.get("complete")),
            "resumed": bool(current.get("resumed")),
            "exported": len(current.get("items") or []) if isinstance(current.get("items"), list) else 0,
            "rows": current.get("rows"),
            "stop_reason": current.get("stopReason"),
            "runtime_ms": current.get("runtimeMs"),
            "max_runtime_ms": current.get("maxRuntimeMs"),
            "wall_ms": int((time.time() - pass_started_at) * 1000),
        }
        attempts.append(attempt)
        _append_saby_trace(trace_path, "pass_finished", **attempt)
        if current.get("complete") or pass_index >= auto_resume_passes:
            _append_saby_trace(
                trace_path,
                "stopping_after_pass",
                pass_index=pass_index + 1,
                complete=bool(current.get("complete")),
                auto_resume_passes=auto_resume_passes,
            )
            break
        pass_index += 1

    if result is None:
        _append_saby_trace(trace_path, "no_result_before_timeout", elapsed_ms=int((time.time() - started_at) * 1000))
        raise ToolError("saby_tenders_csv had no time budget left before collection could start; retry later")

    items = result.get("items")
    if not isinstance(items, list):
        _append_saby_trace(trace_path, "missing_items_list", result_keys=sorted(result.keys()))
        raise ToolError("saby_tenders_csv returned no items list")

    clean_items = [item for item in items if isinstance(item, dict)]
    filename = safe_slug(str(args.get("filename") or "saby_tenders")) + "_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
    target = ensure_inside(paths["downloads"] / filename, root)
    target.write_text(csv_text_for_items(clean_items), encoding="utf-8-sig")
    meta = metadata(paths)
    saby_meta = build_saby_metadata(result, options, clean_items, attempts, paths["site"].name)
    meta.update(
        {
            "saby_tenders": saby_meta,
            "downloads": [str(target)],
            "csv": str(target),
            "saby_trace_log": str(trace_path),
        }
    )
    complete = bool(result.get("complete"))
    if complete and not bool_arg(args, "keep_manual_browser", False):
        meta["release_manual_browser_lock"] = True
    next_tool_call = saby_meta.get("next_tool_call")
    if next_tool_call:
        meta["next_tool_call"] = next_tool_call
    meta.update(
        build_browser_workflow(
            state="page_ready" if complete else "partial_result",
            user_action_required=False,
            recommended_next_action="saby_tenders_csv" if next_tool_call else None,
            recommended_next_args={k: v for k, v in next_tool_call.items() if k != "action"} if next_tool_call else None,
            next_tool_call=next_tool_call,
            user_message_hint=(
                "This CSV is partial. Send it to the user and ask whether to continue from the same browser state."
                if not complete
                else "Collection reached a normal stopping condition."
            ),
            constraints={"ask_user_before_resume": not complete},
        )
    )
    sample = clean_items[:5]
    steps = saby_meta.get("steps") or []
    steps_summary = summarize_steps(steps)
    script_version = str(result.get("scriptVersion") or "(unknown)")
    completeness_warning = (
        "WARNING: collection_complete=false; CSV is partial. Send the CSV, stop this agent run, and ask the user whether to continue. Do not start another saby_tenders_csv call in the same response."
        if not complete
        else "collection_complete=true; target-date collection reached a normal stopping condition."
    )
    next_step_text = (
        "next_step: send the partial CSV to the user, stop this response, and ask whether to continue from the same browser state."
        if not complete
        else "next_step: collection is complete; send the CSV to the user."
    )
    output = "\n".join(
        [
            f"saby_diag skill={SKILL_VERSION} script={script_version} complete={str(complete).lower()} resumed={str(bool(result.get('resumed'))).lower()} reason={result.get('stopReason') or 'none'} steps={steps_summary.get('count', 0)} exported={len(clean_items)} rows={result.get('rows')} target={result.get('targetKey')} runtime_ms={result.get('runtimeMs')} max_runtime_ms={result.get('maxRuntimeMs')}",
            f"attempts: {json.dumps(attempts, ensure_ascii=False)}",
            completeness_warning,
            next_step_text,
            "saby_tenders_csv_ok=true",
            f"skill_version: {SKILL_VERSION}",
            f"script_version: {script_version}",
            f"collection_complete: {str(complete).lower()}",
            f"resumed: {str(bool(result.get('resumed'))).lower()}",
            f"next_action: {result.get('nextAction') or '(none)'}",
            f"next_tool_call: {json_line(next_tool_call) if next_tool_call else '(none)'}",
            f"stop_reason: {result.get('stopReason') or '(none)'}",
            f"steps_summary: {json.dumps(steps_summary, ensure_ascii=False)}",
            f"items_exported: {len(clean_items)}",
            f"rows_seen: {result.get('rows')}",
            f"with_id: {result.get('withId')}",
            f"runtime_ms: {result.get('runtimeMs')}",
            f"max_runtime_ms: {result.get('maxRuntimeMs')}",
            f"target: {result.get('targetText')} / {result.get('targetKey')}",
            f"url: {result.get('url')}",
            f"title: {result.get('title')}",
            f"mode: {result.get('mode')}",
            f"filter_text: {options['filterText'] or '(none)'}",
            f"trace_log: {trace_path}",
            f"steps: {cap_output(json.dumps(steps, ensure_ascii=False), 1800)}",
            f"csv: {target}",
            "",
            *prelude,
            "",
            cap_output(json.dumps(sample, ensure_ascii=False, indent=2), 4000),
        ]
    )
    _append_saby_trace(
        trace_path,
        "action_finished",
        elapsed_ms=int((time.time() - started_at) * 1000),
        complete=complete,
        exported=len(clean_items),
        rows=result.get("rows"),
        stop_reason=result.get("stopReason"),
        csv=str(target),
    )
    return output, meta
