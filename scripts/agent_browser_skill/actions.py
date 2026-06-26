from __future__ import annotations

from agent_browser_skill.actions_auth import action_clear_session, action_login
from agent_browser_skill.actions_batch import action_batch, action_run, normalize_batch_commands
from agent_browser_skill.actions_generic import (
    action_click,
    action_fill,
    action_open,
    action_screenshot,
    action_skills,
    action_snapshot,
    action_start,
    action_wait,
)
from agent_browser_skill.actions_maintenance import (
    action_cleanup,
    action_close,
    action_profile_aliases,
    action_recover,
    action_set_profile_alias,
    action_status,
)
from agent_browser_skill.actions_manual import (
    action_challenge_detected,
    action_close_manual_access,
    action_continue_after_manual,
    action_desktop_open,
    action_desktop_screenshot,
    action_desktop_snapshot,
    action_downloads,
    action_evaluate,
    action_manual_desktop,
    action_navigate_pagination,
    action_read_artifact,
    action_share_session,
    action_stop_desktop,
)
from agent_browser_skill.actions_saby import action_saby_tenders_csv
from agent_browser_skill.core.output import metadata

ACTIONS = {
    "start": action_start,
    "skills": action_skills,
    "open": action_open,
    "snapshot": action_snapshot,
    "click": action_click,
    "fill": action_fill,
    "type": action_fill,
    "wait": action_wait,
    "screenshot": action_screenshot,
    "share_session": action_share_session,
    "manual_desktop": action_manual_desktop,
    "stop_desktop": action_stop_desktop,
    "close_manual_access": action_close_manual_access,
    "desktop_open": action_desktop_open,
    "desktop_snapshot": action_desktop_snapshot,
    "desktop_screenshot": action_desktop_screenshot,
    "evaluate": action_evaluate,
    "read_artifact": action_read_artifact,
    "navigate_pagination": action_navigate_pagination,
    "downloads": action_downloads,
    "saby_tenders_csv": action_saby_tenders_csv,
    "challenge_detected": action_challenge_detected,
    "continue_after_manual": action_continue_after_manual,
    "batch": action_batch,
    "run": action_run,
    "login": action_login,
    "clear_session": action_clear_session,
    "close": action_close,
    "recover": action_recover,
    "status": action_status,
    "profile_aliases": action_profile_aliases,
    "set_profile_alias": action_set_profile_alias,
    "cleanup": action_cleanup,
}
