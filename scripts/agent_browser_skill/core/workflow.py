from __future__ import annotations

from typing import Any


DEFAULT_BROWSER_CONSTRAINTS = {
    "do_not_use_shell": True,
    "do_not_infer_public_host": True,
    "do_not_repeat_tool_discovery": True,
}


def build_browser_workflow(
    *,
    state: str,
    user_action_required: bool,
    recommended_next_action: str | None = None,
    recommended_next_args: dict[str, Any] | None = None,
    next_tool_call: dict[str, Any] | None = None,
    required_next_tool_call: dict[str, Any] | None = None,
    allowed_next_actions: list[str] | None = None,
    forbidden_next_actions: list[str] | None = None,
    artifact_policy: dict[str, Any] | None = None,
    context_policy: dict[str, Any] | None = None,
    external_urls: dict[str, Any] | None = None,
    credentials_to_show_user: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    user_message_hint: str | None = None,
) -> dict[str, Any]:
    merged_constraints = dict(DEFAULT_BROWSER_CONSTRAINTS)
    if constraints:
        merged_constraints.update(constraints)

    workflow: dict[str, Any] = {
        "workflow_state": state,
        "user_action_required": bool(user_action_required),
        "constraints": merged_constraints,
    }
    if recommended_next_action:
        workflow["recommended_next_action"] = recommended_next_action
    if recommended_next_args:
        workflow["recommended_next_args"] = dict(recommended_next_args)
    if next_tool_call:
        workflow["next_tool_call"] = dict(next_tool_call)
    elif recommended_next_action:
        payload = {"action": recommended_next_action}
        if recommended_next_args:
            payload.update(recommended_next_args)
        workflow["next_tool_call"] = payload
    if external_urls:
        workflow["external_urls"] = dict(external_urls)
    if credentials_to_show_user:
        workflow["credentials_to_show_user"] = dict(credentials_to_show_user)
    if user_message_hint:
        workflow["user_message_hint"] = user_message_hint

    meta = {"browser_workflow": workflow}
    meta["workflow_state"] = workflow["workflow_state"]
    meta["user_action_required"] = workflow["user_action_required"]
    meta["constraints"] = workflow["constraints"]
    if "recommended_next_action" in workflow:
        meta["recommended_next_action"] = workflow["recommended_next_action"]
    if "recommended_next_args" in workflow:
        meta["recommended_next_args"] = workflow["recommended_next_args"]
    if "next_tool_call" in workflow:
        meta["next_tool_call"] = workflow["next_tool_call"]
    if required_next_tool_call:
        workflow["required_next_tool_call"] = dict(required_next_tool_call)
        meta["required_next_tool_call"] = workflow["required_next_tool_call"]
    if allowed_next_actions:
        workflow["allowed_next_actions"] = list(allowed_next_actions)
        meta["allowed_next_actions"] = workflow["allowed_next_actions"]
    if forbidden_next_actions:
        workflow["forbidden_next_actions"] = list(forbidden_next_actions)
        meta["forbidden_next_actions"] = workflow["forbidden_next_actions"]
    if artifact_policy:
        workflow["artifact_policy"] = dict(artifact_policy)
        meta["artifact_policy"] = workflow["artifact_policy"]
    if context_policy:
        workflow["context_policy"] = dict(context_policy)
        meta["context_policy"] = workflow["context_policy"]
    if "external_urls" in workflow:
        meta["external_urls"] = workflow["external_urls"]
    if "credentials_to_show_user" in workflow:
        meta["credentials_to_show_user"] = workflow["credentials_to_show_user"]
    if "user_message_hint" in workflow:
        meta["user_message_hint"] = workflow["user_message_hint"]
    return meta
