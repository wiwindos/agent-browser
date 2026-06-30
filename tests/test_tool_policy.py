from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.core.action_schemas import save_state
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
        assert out["suggested_next_action"] in out["next_allowed_actions"] or out["suggested_next_action"] in {"page_markdown", "read_artifact_by_id", "search_artifact"}


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
        assert out["suggested_next_action"] in {"page_markdown", "wait_ready", "read_artifact_by_id", "search_artifact", "open_page"}


def test_blocked_forum_and_fetch_recover_to_markdown(tmp_path: Path) -> None:
    save_state(
        tmp_path,
        {
            "session_id": "browser-session",
            "profile": "4pda.to",
            "current_url": "https://4pda.to/forum/index.php?showtopic=1",
            "phase": "READY",
        },
    )

    for args in [
        {"action": "run", "task": "curl https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "fetch_page", "url": "https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "write_file", "path": str(tmp_path / "parse_4pda.py"), "content": "import urllib.request"},
    ]:
        out = _run(tmp_path, args)
        assert out["error_code"] == "BLOCKED"
        assert out["suggested_next_action"] == "page_markdown"


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
    assert results[0]["suggested_next_action"] == "page_markdown"
    assert results[1]["suggested_next_action"] == "page_markdown"
    assert results[2]["state"]["phase"] == "READY"
    assert results[2]["suggested_next_action"] == "wait_ready"
    assert results[3]["suggested_next_action"] == "page_markdown"
    assert results[3]["next_allowed_actions"][:4] == ["page_markdown", "read_page_md", "search_artifact", "get_page_text"]


def test_observed_4pda_browser_workflow_gate_sequence(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_desktop_open(root, paths, args):
        calls.append("desktop_open")
        return (
            "desktop_opened=true\ncurrent_url: https://4pda.to/forum/index.php?showtopic=1",
            {"current_url": args.get("url"), "text_file": str(tmp_path / "desktop.txt"), "site_key": "4pda.to", "next_tool_call": {"action": "page_markdown"}, "recommended_next_action": "page_markdown"},
        )

    def fake_desktop_snapshot(root, paths, args):
        calls.append("desktop_snapshot")
        return (
            "desktop_snapshot=true\nchallenge_detected: false",
            {"current_url": "https://4pda.to/forum/index.php?showtopic=1", "text_file": str(tmp_path / "snap.txt"), "site_key": "4pda.to", "next_tool_call": {"action": "page_markdown"}, "recommended_next_action": "page_markdown"},
        )

    md_path = tmp_path / "browser-artifacts" / "4pda.to" / "run" / "page.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("# 4PDA\npost body", encoding="utf-8")

    def fake_page_markdown(root, paths, args):
        calls.append("page_markdown")
        return (
            f"page_markdown_ok=true\nartifact_id: md_test\nmarkdown_file: {md_path}\nnext_tool_call: {{\"action\":\"read_page_md\"}}",
            {"markdown_file": str(md_path), "text_file": str(md_path), "artifact_id": "md_test", "site_key": "4pda.to", "next_tool_call": {"action": "read_page_md", "max_chars": 3000}, "recommended_next_action": "read_page_md"},
        )

    def fake_read_page_md(root, paths, args):
        calls.append("read_page_md")
        return "read_page_md_ok=true\n# 4PDA\npost body", {"markdown_file": str(md_path), "artifact_id": "md_test", "read_page_md_used": True, "site_key": "4pda.to"}

    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", {"desktop_open": fake_desktop_open, "desktop_snapshot": fake_desktop_snapshot, "page_markdown": fake_page_markdown, "read_page_md": fake_read_page_md})
    monkeypatch.setattr("agent_browser_skill.runner.manual_desktop_running", lambda root: True)
    monkeypatch.setattr("agent_browser_skill.core.locks.guard_manual_browser_resource", lambda *a, **k: None)

    opened = _run(tmp_path, {"action": "desktop_open", "profile": "4pda.to", "url": "https://4pda.to/forum/index.php?showtopic=1"})
    assert opened["ok"] is True
    assert "PRIMARY_NEXT_TOOL_CALL" in opened["message"]
    assert "next_tool_call" in opened["message"]
    assert opened["suggested_next_action"] == "page_markdown"

    snap = _run(tmp_path, {"action": "desktop_snapshot", "profile": "4pda.to"})
    assert snap["ok"] is True
    assert "PRIMARY_NEXT_TOOL_CALL" in snap["message"]
    assert "page_markdown" in snap["message"]

    for args in [
        {"action": "fetch_page", "url": "https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "run_command", "command": "curl https://4pda.to/forum/index.php?showtopic=1"},
        {"action": "write_file", "path": str(tmp_path / "parse_4pda.py"), "content": "parser fallback"},
    ]:
        blocked = _run(tmp_path, args)
        assert blocked["ok"] is False
        assert blocked["error_code"] == "BLOCKED"
        assert blocked["suggested_next_action"] == "page_markdown"

    md = _run(tmp_path, {"action": "page_markdown", "profile": "4pda.to"})
    assert md["ok"] is True
    assert md["state"]["artifact_id"].startswith("md_") or md["state"]["artifact_id"] == "md_test"
    assert md["suggested_next_action"] == "read_page_md"

    read = _run(tmp_path, {"action": "read_page_md", "profile": "4pda.to"})
    assert read["ok"] is True
    assert "read_page_md_ok=true" in read["message"]
    assert calls.count("page_markdown") == 1


def test_desktop_open_without_url_preserves_4pda_profile_in_error(tmp_path: Path) -> None:
    out = _run(tmp_path, {"action": "desktop_open", "profile": "4pda.to"})
    assert out["ok"] is False
    assert "profile=4pda.to" in out["message"]
    assert "page_markdown" in out["message"]
    assert out["state"]["profile"] == "4pda.to"
    assert "profile=default" not in out["message"]


def test_safe_profile_blocks_raw_execution_actions(tmp_path):
    for action in ("evaluate", "run", "command.run", "plugin.run"):
        out = _run(tmp_path, {"action": action, "profile": "safe", "script": "1+1", "task": "echo hi"})
        assert out["success"] is False
        assert "BLOCKED_SAFE_PROFILE" in out["message"]
