from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.runner import run_request


def _run(tmp_path: Path, args: dict) -> dict:
    return run_request({"args": args, "context": {"cwd": str(tmp_path), "session_id": "browser-session", "source": "skill_agent-browser_browser"}})


def test_active_browser_blocks_generic_tools_with_normalized_result(tmp_path: Path) -> None:
    for action in ["run_command", "read_file", "list_directory"]:
        out = _run(tmp_path, {"action": action, "command": "echo should-not-run", "path": "/tmp"})
        assert out["success"] is False
        assert out["ok"] is False
        assert out["error_code"] == "BLOCKED"
        assert out["action"] == action
        assert out["session_id"] == "browser-session"
        assert out["state"]["session_id"] == "browser-session"
        assert out["suggested_next_action"] in out["next_allowed_actions"] or out["suggested_next_action"] in {"read_artifact_by_id", "search_artifact"}


def test_active_browser_blocks_protected_paths_and_command_like_requests(tmp_path: Path) -> None:
    blocked = [
        {"action": "run", "task": 'find /workspace -path "/browser-artifacts"'},
        {"action": "run", "task": "curl https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "run", "task": "pip install requests"},
        {"action": "run", "task": "python3 << 'PYEOF'\nprint('x')\nPYEOF"},
        {"action": "open_page", "url": "file:///workspace/u/browser-artifacts/x.txt"},
        {"action": "open_page", "url": "file:///data/skills/agent-browser/SKILL.md"},
    ]
    for args in blocked:
        out = _run(tmp_path, args)
        assert out["error_code"] == "BLOCKED"
        assert out["ok"] is False
        assert out["suggested_next_action"] in {"wait_ready", "read_artifact_by_id", "search_artifact", "extract_forum_posts", "open_page"}


def test_debug_admin_can_bypass_active_browser_policy_to_existing_action(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_action(root, paths, args):
        calls.append(args["action"])
        return "ran", {}

    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", {"run": fake_action})
    out = _run(tmp_path, {"action": "run", "task": "pip install requests", "debug_admin": True})
    assert out["success"] is True
    assert calls == ["run"]


def test_alias_normalizer_warns_without_failing(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_open(root, paths, args):
        calls.append(args)
        return "", {"current_url": args["url"]}

    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", {"open": fake_open})
    out = _run(tmp_path, {"action": "open", "url_or_page": "https://example.test"})

    assert out["ok"] is True
    assert calls[0]["url"] == "https://example.test"
    assert out["message"] == "open completed"
    assert "normalized parameter url_or_page -> url" in out["metadata"]["warnings"]


def test_browser_sequence_returns_structured_guidance_not_shell(tmp_path: Path, monkeypatch) -> None:
    def fake_desktop_open(root, paths, args):
        return "desktop opened", {"current_url": args["url"], "text_file": str(tmp_path / "desktop.txt")}

    def fake_desktop_snapshot(root, paths, args):
        return "desktop snapshot", {"current_url": "https://example.test/desktop", "text_file": str(tmp_path / "snap.txt")}

    def fake_open(root, paths, args):
        return "open ok", {"current_url": args["url"], "snapshot_file": str(tmp_path / "open.json")}

    actions = {
        "desktop_open": fake_desktop_open,
        "desktop_snapshot": fake_desktop_snapshot,
        "open": fake_open,
        "status": __import__("agent_browser_skill.actions_maintenance", fromlist=["action_status"]).action_status,
    }
    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", actions)
    monkeypatch.setattr("agent_browser_skill.runner.manual_desktop_running", lambda root: True)
    monkeypatch.setattr("agent_browser_skill.core.locks.guard_manual_browser_resource", lambda *a, **k: None)

    results = [
        _run(tmp_path, {"action": "desktop_open", "url": "https://example.test/desktop"}),
        _run(tmp_path, {"action": "desktop_snapshot"}),
        _run(tmp_path, {"action": "open", "url": "https://example.test/open"}),
        _run(tmp_path, {"action": "status"}),
    ]

    for out in results:
        assert out["ok"] is True
        assert out["message"].strip()
        assert {"ok", "action", "session_id", "state", "error_code", "message", "suggested_next_action", "next_allowed_actions"} <= set(out)
        assert out["suggested_next_action"] not in {"run", "run_command", "read_file", "shell"}

    assert results[0]["state"]["phase"] == "READY"
    assert results[0]["suggested_next_action"] == "scroll_until_stable"
    assert results[2]["state"]["phase"] == "READY"
    assert results[2]["suggested_next_action"] == "wait_ready"
    assert results[3]["suggested_next_action"] == "get_page_text"
    assert results[3]["next_allowed_actions"][:4] == ["get_page_text", "extract_links", "extract_forum_posts", "screenshot"]
