from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_browser_skill.core.args import bool_arg, int_arg
from agent_browser_skill.errors import ToolError


def _domain_root() -> Path:
    return Path(__file__).resolve().parent


def collector_script_path() -> Path:
    return _domain_root() / "collector.js"


def selectors_path() -> Path:
    return _domain_root() / "selectors.json"


def collector_script_text() -> str:
    path = collector_script_path()
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ToolError(f"missing Saby collector script: {path.name}") from exc


def load_selectors() -> dict[str, str]:
    path = selectors_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"missing Saby selector config: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"invalid Saby selector config: {exc}") from exc

    selectors = {
        "row": str(raw.get("row") or "").strip(),
        "next": str(raw.get("next") or "").strip(),
        "date": str(raw.get("date") or "").strip(),
    }
    if not all(selectors.values()):
        raise ToolError("Saby selector config must define row, next, and date selectors")
    return selectors


def json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_next_tool_call(
    profile: str,
    mode: str,
    target_date: str = "",
    filter_text: str = "",
    subscription_text: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "saby_tenders_csv",
        "profile": profile,
        "mode": (mode or "yesterday").strip().lower() or "yesterday",
        "resume_state": True,
    }
    if target_date:
        payload["target_date"] = target_date
    if filter_text:
        payload["filter_text"] = filter_text
    if subscription_text:
        payload["subscription_text"] = subscription_text
    return payload


def build_prepared_state(profile: str, args: dict[str, Any], remaining_after_start_ms: int) -> tuple[dict[str, Any], dict[str, Any]]:
    next_tool_call = build_next_tool_call(
        profile=profile,
        mode=str(args.get("mode") or "yesterday"),
        target_date=str(args.get("target_date") or "").strip(),
        filter_text=str(args.get("filter_text") or "").strip(),
        subscription_text=str(args.get("subscription_text") or args.get("subscription") or "").strip(),
    )
    state = {
        "complete": False,
        "prepared": True,
        "stop_reason": "manual desktop started; collection deferred to next tool call",
        "next_action": "call action=saby_tenders_csv with the same profile/mode/target_date and resume_state=true without url",
        "next_tool_call": next_tool_call,
        "remaining_after_start_ms": remaining_after_start_ms,
    }
    return state, next_tool_call


def build_saby_options(args: dict[str, Any], max_runtime_ms: int) -> dict[str, Any]:
    selectors = load_selectors()
    options = {
        "template": str(args.get("template") or "https://trade.saby.ru/page/tender-card/{id}"),
        "filterText": str(args.get("filter_text") or args.get("text") or "").strip(),
        "subscriptionText": str(args.get("subscription_text") or args.get("subscription") or "").strip(),
        "targetDate": str(args.get("target_date") or "").strip(),
        "mode": str(args.get("mode") or "yesterday").strip().lower(),
        "dateText": str(args.get("date_text") or "").strip(),
        "delayAfterClick": int_arg(args, "delay_after_click", 350, 0, 10000),
        "rowChangeTimeoutMs": int_arg(args, "row_change_timeout_ms", 2500, 250, 10000),
        "maxClicks": int_arg(args, "max_clicks", 300, 1, 2000),
        "stopAfterNoGrowth": int_arg(args, "stop_after_no_growth", 4, 1, 50),
        "olderBatchConfirmations": int_arg(args, "older_batch_confirmations", 3, 1, 20),
        "maxRuntimeMs": max_runtime_ms,
        "initialRowsTimeoutMs": int_arg(args, "initial_rows_timeout_ms", 8000, 0, 60000),
        "resumeState": bool_arg(args, "resume_state", True),
        "resetState": bool_arg(args, "reset_state", False),
        "downloadInBrowser": False,
        "selectors": selectors,
        "rowSelector": selectors["row"],
        "nextSelector": selectors["next"],
        "dateSelector": selectors["date"],
    }
    try:
        options["limit"] = max(0, int(args.get("limit") or 0))
    except (TypeError, ValueError):
        options["limit"] = 0
    return options


def build_saby_metadata(
    result: dict[str, Any],
    options: dict[str, Any],
    clean_items: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    profile: str,
) -> dict[str, Any]:
    complete = bool(result.get("complete"))
    next_tool_call = None if complete else build_next_tool_call(
        profile=profile,
        mode=str(options.get("mode") or "yesterday"),
        target_date=str(options.get("targetDate") or "").strip(),
        filter_text=str(options.get("filterText") or "").strip(),
        subscription_text=str(options.get("subscriptionText") or "").strip(),
    )
    steps = result.get("steps")
    if not isinstance(steps, list):
        steps = []
    selectors = load_selectors()
    return {
        "url": result.get("url"),
        "title": result.get("title"),
        "target_text": result.get("targetText"),
        "target_key": result.get("targetKey"),
        "script_version": result.get("scriptVersion"),
        "mode": result.get("mode"),
        "filter_text": options.get("filterText") or "",
        "subscription_text": options.get("subscriptionText") or "",
        "subscription_selection": result.get("subscriptionSelection"),
        "stop_reason": result.get("stopReason"),
        "complete": complete,
        "prepared": False,
        "resumed": bool(result.get("resumed")),
        "next_action": result.get("nextAction"),
        "next_tool_call": next_tool_call,
        "steps": steps,
        "stats": {
            "rows": result.get("rows"),
            "with_id": result.get("withId"),
            "exported": len(clean_items),
            "steps": len(steps),
            "runtime_ms": result.get("runtimeMs"),
            "max_runtime_ms": result.get("maxRuntimeMs"),
        },
        "rows": result.get("rows"),
        "with_id": result.get("withId"),
        "exported": len(clean_items),
        "runtime_ms": result.get("runtimeMs"),
        "max_runtime_ms": result.get("maxRuntimeMs"),
        "attempts": attempts,
        "selectors": selectors,
    }


def summarize_steps(steps: Any) -> dict[str, Any]:
    if not isinstance(steps, list) or not steps:
        return {"count": 0}
    return {
        "count": len(steps),
        "first": steps[0],
        "last": steps[-1],
    }
