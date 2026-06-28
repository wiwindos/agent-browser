from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.actions_generic import action_snapshot
from agent_browser_skill.actions_manual import (
    action_desktop_open,
    action_desktop_snapshot,
    action_navigate_pagination,
    action_read_artifact,
)
from agent_browser_skill.core.config import LOCKLESS_ACTIONS
from agent_browser_skill.core.artifacts import cleanup_note
from agent_browser_skill.core.paths import paths_for
from agent_browser_skill.errors import ToolError
from agent_browser_skill.domains.saby.state import build_prepared_state, build_saby_options
from agent_browser_skill.runner import run_request


def _paths(tmp_path: Path, action: str = "snapshot") -> dict[str, Path]:
    return paths_for(tmp_path, {"action": action, "profile": "example", "url": "https://example.com"})


def test_empty_snapshot_returns_read_artifact_next_tool_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paths = _paths(tmp_path, "snapshot")

    def fake_ab(root: Path, paths: dict[str, Path], args: dict[str, object], cmd: list[str]) -> tuple[int, str]:
        assert cmd == ["snapshot", "-i", "--json"]
        return 0, json.dumps({"title": "", "refs": []})

    monkeypatch.setattr("agent_browser_skill.actions_generic.ab", fake_ab)

    output, meta = action_snapshot(tmp_path, paths, {"action": "snapshot", "profile": "example"})

    snapshot_file = meta["snapshot_file"]
    assert "refs_count: 0" in output
    assert "next_step: Snapshot is empty" in output
    assert "Do not pass the artifact directory" in output
    assert f'"path": "{snapshot_file}"' in output
    assert "fallback_after_read" in output


def test_read_artifact_directory_resolves_to_best_readable_file(tmp_path: Path) -> None:
    paths = _paths(tmp_path, "snapshot")
    screenshot = paths["screenshots"] / "screenshot.png"
    screenshot.write_bytes(b"not text")
    state = paths["logs"] / "desktop-snapshot-state.json"
    state.write_text('{"title":"Example"}', encoding="utf-8")
    text_file = paths["logs"] / "desktop-snapshot-state-text.txt"
    text_file.write_text("Useful page text", encoding="utf-8")

    output, meta = action_read_artifact(tmp_path, paths, {"action": "read_artifact", "path": str(paths["artifact"])})

    assert "artifact_read_ok=true" in output
    assert f"artifact_directory: {paths['artifact']}" in output
    assert f"artifact_directory_resolved_file: {text_file}" in output
    assert "Useful page text" in output
    assert meta["artifact_file"] == str(text_file)
    assert meta["artifact_directory_resolved_file"] == str(text_file)


def test_read_artifact_directory_errors_when_no_readable_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path, "snapshot")
    screenshot = paths["screenshots"] / "screenshot.png"
    screenshot.write_bytes(b"not text")

    with pytest.raises(ToolError) as exc_info:
        action_read_artifact(tmp_path, paths, {"action": "read_artifact", "path": str(paths["artifact"])})

    assert "found no readable text/json/html/csv files" in str(exc_info.value)


def test_saby_subscription_text_is_preserved_in_options_and_resume_call() -> None:
    args = {
        "mode": "yesterday",
        "subscription_text": "БПЛА",
        "filter_text": "дрон",
        "delay_after_click": 0,
    }

    options = build_saby_options(args, max_runtime_ms=60_000)
    _state, next_tool_call = build_prepared_state("saby", args, remaining_after_start_ms=30_000)

    assert options["subscriptionText"] == "БПЛА"
    assert options["filterText"] == "дрон"
    assert options["delayAfterClick"] == 0
    assert options["rowChangeTimeoutMs"] == 2500
    assert options["initialRowsTimeoutMs"] == 8000
    assert next_tool_call["subscription_text"] == "БПЛА"
    assert next_tool_call["filter_text"] == "дрон"


def test_desktop_open_guides_data_extraction_before_screenshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paths = _paths(tmp_path, "desktop_open")

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.manual_desktop_running", lambda root: True)
    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.desktop_navigate", lambda args, url: None)
    monkeypatch.setattr(
        "agent_browser_skill.actions_manual.desktop.desktop_page_state",
        lambda args: {
            "url": "https://example.com/forum",
            "title": "Forum",
            "htmlLength": 123,
            "text": "Forum post text",
        },
    )
    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.state_needs_manual_action", lambda state: False)

    output, meta = action_desktop_open(
        tmp_path,
        paths,
        {"action": "desktop_open", "profile": "example", "url": "https://example.com/forum"},
    )

    assert "text_file:" in output
    assert "read the exact text_file with action=read_artifact" in output
    assert "until the requested page data is extracted" in output
    assert "next_tool_call:" in output
    assert "desktop_screenshot" in output
    assert "read_file" in output
    assert "action=run" in output
    assert meta["recommended_next_action"] == "read_artifact"
    assert meta["next_tool_call"]["action"] == "read_artifact"
    assert meta["next_tool_call"]["max_chars"] == 3000
    assert meta["required_next_tool_call"] == meta["next_tool_call"]
    assert "desktop_screenshot" in meta["forbidden_next_actions"]
    assert meta["constraints"]["must_read_exact_text_file_first"] is True
    assert meta["next_tool_call"]["path"].endswith("desktop-open-state-text.txt")
    assert meta["text_file"].endswith("desktop-open-state-text.txt")
    assert meta["page_kind"] == "forum_thread"
    assert meta["recommended_followup_after_read"]["action"] == "navigate_pagination"


def test_desktop_snapshot_guides_read_artifact_before_screenshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path, "desktop_snapshot")

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.manual_desktop_running", lambda root: True)
    monkeypatch.setattr(
        "agent_browser_skill.actions_manual.desktop.desktop_page_state",
        lambda args: {
            "url": "https://example.com/forum/index.php?showtopic=1",
            "title": "Forum",
            "htmlLength": 123,
            "text": "Forum post text",
        },
    )
    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.state_needs_manual_action", lambda state: False)

    _output, meta = action_desktop_snapshot(tmp_path, paths, {"action": "desktop_snapshot", "profile": "example"})

    assert meta["recommended_next_action"] == "read_artifact"
    assert meta["next_tool_call"]["action"] == "read_artifact"
    assert meta["next_tool_call"]["path"].endswith("desktop-snapshot-state-text.txt")
    assert meta["required_next_tool_call"] == meta["next_tool_call"]
    assert "run_command" in meta["forbidden_next_actions"]
    assert meta["page_kind"] == "forum_thread"


def test_navigate_pagination_guides_read_artifact_after_navigation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path, "navigate_pagination")
    calls: list[str] = []

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.manual_desktop_running", lambda root: True)
    monkeypatch.setattr(
        "agent_browser_skill.actions_manual.cdp.cdp_eval",
        lambda port, script: {"href": "https://example.com/forum/index.php?showtopic=1&st=500", "text": "50", "reason": "number"},
    )

    def fake_navigate(args: dict[str, object], url: str) -> None:
        calls.append(url)

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.desktop_navigate", fake_navigate)
    monkeypatch.setattr(
        "agent_browser_skill.actions_manual.desktop.desktop_page_state",
        lambda args: {
            "url": "https://example.com/forum/index.php?showtopic=1&st=500",
            "title": "Forum last page",
            "htmlLength": 456,
            "text": "Fresh forum post text",
        },
    )
    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.state_needs_manual_action", lambda state: False)

    output, meta = action_navigate_pagination(
        tmp_path,
        paths,
        {"action": "navigate_pagination", "profile": "example", "target": "last"},
    )

    assert calls == ["https://example.com/forum/index.php?showtopic=1&st=500"]
    assert "navigate_pagination_ok=true" in output
    assert "next_tool_call:" in output
    assert meta["recommended_next_action"] == "read_artifact"
    assert meta["next_tool_call"]["action"] == "read_artifact"
    assert meta["next_tool_call"]["max_chars"] == 6000
    assert meta["next_tool_call"]["path"].endswith("pagination-last-state-text.txt")


def test_read_artifact_query_returns_matching_context(tmp_path: Path) -> None:
    paths = _paths(tmp_path, "read_artifact")
    text_file = paths["logs"] / "posts.txt"
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(
        "old post\n26.06.26 nothing\nmiddle\n27.06.26 target post\nnext line\n",
        encoding="utf-8",
    )

    output, meta = action_read_artifact(
        tmp_path,
        paths,
        {"action": "read_artifact", "path": str(text_file), "query": "27.06.26", "context_lines": 1},
    )

    assert "artifact_filter: query=27.06.26" in output
    assert "27.06.26 target post" in output
    assert "next line" in output
    assert meta["artifact_mode"] == "filter"
    assert meta["artifact_filter_matches"] == 1


def test_unknown_send_file_action_explains_platform_boundary(tmp_path: Path) -> None:
    payload = run_request({"args": {"action": "send_file"}, "context": {"cwd": str(tmp_path)}})

    assert payload["success"] is False
    assert "send_file is not an agent-browser action" in payload["error"]
    assert "read_artifact" in payload["error"]


def test_desktop_open_recovers_stale_manual_desktop_cdp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paths = _paths(tmp_path, "desktop_open")
    calls: list[str] = []

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.manual_desktop_running", lambda root: True)

    def stale_navigate(args: dict[str, object], url: str) -> None:
        calls.append(f"navigate:{url}")
        raise ToolError("manual desktop CDP is not reachable on 127.0.0.1:9222: timed out")

    def fake_stop(root: Path) -> str:
        calls.append("stop")
        return "stopped: chrome"

    def fake_unlock(profile: Path) -> list[str]:
        calls.append(f"unlock:{profile.name}")
        return []

    def fake_manual(root: Path, paths: dict[str, Path], args: dict[str, object]) -> tuple[str, dict[str, object]]:
        calls.append("manual")
        return "manual_desktop_started=true", {"manual_desktop_active": True}

    monkeypatch.setattr("agent_browser_skill.actions_manual.desktop.desktop_navigate", stale_navigate)
    monkeypatch.setattr("agent_browser_skill.actions_manual.process_runtime.stop_manual_desktop", fake_stop)
    monkeypatch.setattr("agent_browser_skill.actions_manual.process_runtime.unlock_profile", fake_unlock)
    monkeypatch.setattr("agent_browser_skill.actions_manual.action_manual_desktop", fake_manual)

    output, meta = action_desktop_open(
        tmp_path,
        paths,
        {"action": "desktop_open", "profile": "example", "url": "https://example.com"},
    )

    assert calls == ["navigate:https://example.com", "stop", "unlock:example.com", "manual"]
    assert "desktop_open_recovered_stale_cdp=true" in output
    assert "manual_desktop_started=true" in output
    assert meta["desktop_open_started_manual_desktop"] is True
    assert meta["desktop_open_recovered_stale_cdp"] is True
    assert meta["manual_desktop_stop"] == "stopped: chrome"


def test_cleanup_is_lockless_for_timeout_recovery() -> None:
    assert "cleanup" in LOCKLESS_ACTIONS


def test_cleanup_removes_legacy_browser_use_when_workspace_is_over_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy_cache = tmp_path / ".browser-use" / "Default" / "Cache"
    legacy_cache.mkdir(parents=True)
    (legacy_cache / "blob.bin").write_bytes(b"x" * 2048)
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")

    monkeypatch.setattr("agent_browser_skill.core.artifacts.WORKSPACE_SOFT_LIMIT_BYTES", 1)

    output = cleanup_note(tmp_path)

    assert not (tmp_path / ".browser-use").exists()
    assert (tmp_path / "keep.txt").exists()
    assert "removed legacy browser-use data .browser-use" in output
