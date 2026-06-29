from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_browser_skill.browser import cdp, desktop
from agent_browser_skill.core.args import timeout_from
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.core.snapshot_artifacts import write_json_artifact
from agent_browser_skill.extractors import filter_posts_by_date, normalize_timestamp, short_summary, summarize_posts
from agent_browser_skill.errors import ToolError


def _page_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Return a compact structured page payload using in-browser typed extraction."""
    limit = int(args.get("limit") or 50)
    script = _forum_posts_script(limit)
    data = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script, timeout=timeout_from(args))
    if not isinstance(data, dict):
        raise ToolError("extractor returned an unexpected payload")
    return data


def _forum_posts_script(limit: int) -> str:
    payload = json.dumps({"limit": limit}, ensure_ascii=False)
    return rf"""
(() => {{
 const args = {payload};
 const norm = (s) => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
 const cleanPostText = (el) => {{
   const clone = el.cloneNode(true);
   clone.querySelectorAll('script,style,noscript,.signature,.edit,.post-edit,.post_footer,.post-footer,.post_controls,.ipbmenu_content,.rep_bar,.hidetop,blockquote,.quote').forEach(n => n.remove());
   return norm(clone.innerText || clone.textContent || '');
 }};
 const links = (el) => Array.from(el.querySelectorAll('a[href]')).map(a => ({{text:norm(a.innerText || a.textContent).slice(0,200), href:a.href}}));
 const pick = (el, selectors) => {{ for (const sel of selectors) {{ const n = el.querySelector(sel); if (n && norm(n.innerText || n.textContent || n.getAttribute('title') || n.getAttribute('datetime'))) return n; }} return null; }};
 const dateFromText = (text) => {{
   const m = text.match(/(?:Сегодня|Вчера),?\s*\d{{1,2}}:\d{{2}}\s*(?:\|#\d+)?|\d{{1,2}}[.\-/]\d{{1,2}}[.\-/]\d{{2,4}},?\s*\d{{1,2}}:\d{{2}}(?:\s*\|#\d+)?/i);
   return m ? norm(m[0]) : '';
 }};
 const postIdFrom = (el, i) => {{
   const id = el.id || el.getAttribute('data-post-id') || pick(el, ['a[href*=\"#entry\"],a[name^=\"entry\"],a[id^=\"entry\"]'])?.getAttribute('name') || '';
   const number = norm(el.innerText).match(/\|#(\d+)/)?.[1];
   return id || (number ? `post-${{number}}` : `post-${{i+1}}`);
 }};
 const is4pda = /4pda\.(to|ru)/i.test(location.href) || !!document.querySelector('[id^="entry"],.post_body,.post_header,.postcolor');
 const selectors = is4pda
   ? ['[id^="entry"]','div[id^="post-"]','.post_block','.topic_post']
   : ['article','.post','.message','.topic-post','[class*="post"]'];
 let nodes = Array.from(document.querySelectorAll(selectors.join(','))).filter(el => norm(el.innerText).length > 20);
 const seen = new Set();
 nodes = nodes.filter(el => {{ const key = postIdFrom(el, 0) + ':' + norm(el.innerText).slice(0,300); if (seen.has(key)) return false; seen.add(key); return true; }}).slice(0, args.limit);
 const posts = [];
 for (const [i, el] of nodes.entries()) {{
   const authorNode = pick(el, ['.normalname','.name','.nick','.post-author-name','.author,[itemprop="author"]','[class*="author"]','[class*="nick"]']);
   const dateNode = pick(el, ['.post_date','.post-date','.date','.posted','time','[datetime]','[class*="date"]','[class*="time"]']);
   const body = pick(el, ['.post_body','.postcolor','.post-content','.message-content','.content,[class*="body"]']) || el;
   const rawHeader = norm((dateNode && (dateNode.getAttribute('datetime') || dateNode.innerText || dateNode.textContent)) || '') || dateFromText(norm(el.innerText).slice(0,500));
   posts.push({{post_id:postIdFrom(el, i), author:norm(authorNode?.innerText || authorNode?.textContent || ''), datetime_raw:rawHeader, datetime_iso:null, text:cleanPostText(body), links:links(body), short_summary:''}});
 }}
 const article = {{title:document.title, text:norm(document.querySelector('article,main')?.innerText || document.body?.innerText || ''), links:links(document)}};
 const tables = Array.from(document.querySelectorAll('table')).slice(0,20).map(t => Array.from(t.rows).map(r => Array.from(r.cells).map(c => norm(c.innerText))));
 const search_results = Array.from(document.querySelectorAll('a[href]')).filter(a => norm(a.innerText).length > 3).slice(0,50).map(a => ({{title:norm(a.innerText), url:a.href, snippet:norm(a.closest('li,article,div')?.innerText || '').slice(0,500)}}));
 const pagination = Array.from(document.querySelectorAll('a[href*="st="]')).map(a => ({{text:norm(a.innerText || a.textContent), href:a.href}}));
 return {{url:location.href,title:document.title, adapter:is4pda?'4pda':'generic_forum', confidence:is4pda?0.9:(posts.length?0.55:0.2), pagination, posts, article, tables, search_results}};
}})()
"""


def _write(root: Path, paths: dict[str, Path], prefix: str, payload: Any) -> tuple[str, dict[str, Any]]:
    f = write_json_artifact(root, paths, prefix, payload)
    meta = metadata(paths)
    artifact_id = __import__("agent_browser_skill.core.action_schemas", fromlist=["opaque_id"]).opaque_id(f, "art")
    snapshot_file = f if prefix == "forum-posts" else None
    meta.update({"artifact_file": str(f), "artifact_id": artifact_id, "goal_status": "answer_ready"})
    if snapshot_file:
        meta.update({"snapshot_file": str(snapshot_file), "snapshot_id": __import__("agent_browser_skill.core.action_schemas", fromlist=["opaque_id"]).opaque_id(snapshot_file, "snap")})
    count = len(payload.get("posts", [])) if isinstance(payload, dict) else (len(payload) if isinstance(payload, list) else 0)
    preview = payload.get("preview", []) if isinstance(payload, dict) else []
    return "\n".join([f"{prefix}_ok=true", f"artifact_id: {artifact_id}", *( [f"snapshot_id: {meta['snapshot_id']}"] if "snapshot_id" in meta else []), f"count: {count}", "preview:", cap_output(json.dumps(preview, ensure_ascii=False, indent=2), 3000)]), meta


def action_extract_forum_posts(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = _page_payload(args); requested = str(args.get("adapter") or "auto")
    adapter = data.get("adapter") if requested in {"auto", "4pda", "generic_forum"} and (requested == "auto" or requested == data.get("adapter")) else "generic_forum"
    posts = data.get("posts") if isinstance(data.get("posts"), list) else []
    for p in posts:
        p["datetime_iso"] = normalize_timestamp(p.get("datetime_raw"))
        p["short_summary"] = short_summary(str(p.get("text") or ""))
    if args.get("date_filter"):
        posts = filter_posts_by_date(posts, str(args.get("date_filter")))
    limit = int(args.get("limit") or 50)
    posts = posts[:limit]
    preview = [{"post_id": p.get("post_id"), "author": p.get("author"), "datetime_raw": p.get("datetime_raw"), "short_summary": p.get("short_summary")} for p in posts[:5]]
    payload = {"adapter": adapter, "confidence": data.get("confidence", 0.0), "goal_status": "extracted", "source_url": data.get("url"), "pagination": data.get("pagination", [])[:20], "posts": posts, "count": len(posts), "preview": preview}
    return _write(root, paths, "forum-posts", payload)

def action_extract_article(root, paths, args):
    return _write(root, paths, "article", _page_payload(args).get("article", {}))

def action_extract_table(root, paths, args):
    return _write(root, paths, "tables", _page_payload(args).get("tables", []))

def action_extract_search_results(root, paths, args):
    return _write(root, paths, "search-results", _page_payload(args).get("search_results", []))

def action_extract_updates_by_date(root, paths, args):
    data = _page_payload(args); posts = data.get("posts") if isinstance(data.get("posts"), list) else []
    for p in posts: p["datetime_iso"] = normalize_timestamp(p.get("datetime_raw")); p["short_summary"] = short_summary(str(p.get("text") or ""))
    return _write(root, paths, "updates-by-date", {"goal_status":"extracted", "date_filter": args.get("date") or "yesterday", "posts": filter_posts_by_date(posts, str(args.get("date") or "yesterday"))})

def action_filter_by_date(root, paths, args):
    raw = args.get("posts")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict): raw = raw.get("posts")
    if not isinstance(raw, list): raise ToolError("filter_by_date requires posts array")
    return _write(root, paths, "filtered-posts", {"goal_status":"extracted", "posts": filter_posts_by_date(raw, str(args.get("date") or "yesterday"))})

def action_summarize_posts(root, paths, args):
    raw = args.get("posts")
    if isinstance(raw, str): raw = json.loads(raw)
    if isinstance(raw, dict): raw = raw.get("posts")
    if not isinstance(raw, list): raise ToolError("summarize_posts requires posts array")
    return _write(root, paths, "post-summaries", {"goal_status":"answer_ready", **summarize_posts(raw)})
