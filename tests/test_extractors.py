from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_browser_skill.actions_extractors import action_extract_forum_posts
from agent_browser_skill.core.paths import paths_for
from agent_browser_skill.extractors import filter_posts_by_date, normalize_timestamp, summarize_posts
from agent_browser_skill.runner import run_request


def test_normalized_date_filter_does_not_grep_raw_date_strings() -> None:
    now = datetime(2026, 6, 29, 12, tzinfo=timezone.utc)
    posts = [
        {"post_id": "a", "datetime_raw": "вчера, 23:10", "text": "fresh"},
        {"post_id": "b", "datetime_raw": "28.06.26, 10:00", "text": "also fresh"},
        {"post_id": "c", "datetime_raw": "сегодня, 09:00", "text": "new"},
    ]
    assert normalize_timestamp("вчера, 23:10", now=now) == "2026-06-28T23:10:00+00:00"
    assert [p["post_id"] for p in filter_posts_by_date(posts, "yesterday", now=now)] == ["a", "b"]


def test_extract_forum_posts_adapter_and_fields(monkeypatch, tmp_path: Path) -> None:
    paths = paths_for(tmp_path, {"action": "extract_forum_posts", "profile": "example"})
    payload = {
        "adapter": "4pda",
        "confidence": 0.85,
        "posts": [
            {"post_id": "entry1", "author": "User", "datetime_raw": "28.06.26, 10:00", "text": "Long forum text", "links": [{"href": "https://x", "text": "x"}], "short_summary": ""}
        ],
    }
    monkeypatch.setattr("agent_browser_skill.actions_extractors.cdp.cdp_eval", lambda *a, **k: payload)
    output, meta = action_extract_forum_posts(tmp_path, paths, {"action": "extract_forum_posts", "adapter": "4pda"})
    data = json.loads(Path(meta["artifact_file"]).read_text(encoding="utf-8"))
    assert "forum-posts_ok=true" in output
    assert data["adapter"] == "4pda"
    assert data["confidence"] == 0.85
    assert data["goal_status"] == "extracted"
    post = data["posts"][0]
    assert set(["post_id", "author", "datetime_raw", "datetime_iso", "text", "links", "short_summary"]).issubset(post)
    assert post["datetime_iso"] == "2026-06-28T10:00:00+00:00"
    assert meta["goal_status"] == "answer_ready"


def test_golden_forum_extraction_contract_has_no_raw_eval_or_bloat(monkeypatch, tmp_path: Path) -> None:
    calls = []
    def fake_action(root, paths, args):
        calls.append(args["action"])
        if args["action"] == "extract_forum_posts":
            return "ok", {"artifact_file": str(tmp_path / "posts.json"), "goal_status": "answer_ready"}
        return "ok", {"goal_status": "ok"}
    monkeypatch.setattr("agent_browser_skill.runner.ACTIONS", {k: fake_action for k in ["open", "wait_ready", "scroll_until_stable", "extract_forum_posts"]})
    for action in ["open_page", "wait_ready", "scroll_until_stable", "extract_forum_posts"]:
        args = {"action": action, "profile": "p"}
        if action == "open_page": args["url"] = "https://4pda.to/forum/index.php?showtopic=1"
        if action == "extract_forum_posts": args["adapter"] = "4pda"
        out = run_request({"args": args, "context": {"cwd": str(tmp_path), "session_id": "golden"}})
        assert out["success"] is True
        assert str(tmp_path) not in json.dumps(out, ensure_ascii=False)
        assert "goal_status" in json.dumps(out, ensure_ascii=False)
    assert calls == ["open", "wait_ready", "scroll_until_stable", "extract_forum_posts"]
    assert "evaluate" not in calls
    assert len(json.dumps(calls)) < 500


def test_summarize_posts_separate_structured_step() -> None:
    summary = summarize_posts([{"post_id": "1", "author": "A", "datetime_iso": "2026-06-28T10:00:00+00:00", "text": "First sentence. Details."}])
    assert summary["posts"][0]["post_id"] == "1"
    assert summary["summary"].startswith("Structured 1 posts")
