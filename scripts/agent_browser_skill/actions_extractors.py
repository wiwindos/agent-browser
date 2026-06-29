from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_browser_skill.browser import cdp, desktop
from agent_browser_skill.core.args import int_arg, timeout_from
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.core.snapshot_artifacts import write_json_artifact
from agent_browser_skill.extractors import filter_posts_by_date, normalize_timestamp, short_summary, summarize_posts
from agent_browser_skill.errors import ToolError


def _page_payload(args: dict[str, Any]) -> dict[str, Any]:
    script = r"""
(() => {
 const norm=s=>(s||'').replace(/\s+/g,' ').trim();
 const links=el=>Array.from(el.querySelectorAll('a[href]')).map(a=>({text:norm(a.innerText||a.textContent).slice(0,200), href:a.href}));
 const posts=[];
 const is4pda=/4pda\.(to|ru)|4pda/i.test(location.href)||!!document.querySelector('[id^="entry"],.post_body,.post_header');
 let nodes=Array.from(document.querySelectorAll('[id^="entry"], article, .post, .message, .topic-post, [class*="post"]')).filter(el=>norm(el.innerText).length>20);
 const seen=new Set(); nodes=nodes.filter(el=>{const t=norm(el.innerText).slice(0,1000); if(seen.has(t)) return false; seen.add(t); return true;}).slice(0,200);
 for (const [i,el] of nodes.entries()) {
   const id=el.id||el.getAttribute('data-post-id')||el.querySelector('[id^="entry"]')?.id||`post-${i+1}`;
   const author=norm(el.querySelector('.name,.nick,.author,[itemprop="author"],[class*="author"],[class*="nick"]')?.innerText||'');
   const dt=norm(el.querySelector('time,.date,.posted,[datetime],[class*="date"],[class*="time"]')?.getAttribute('datetime')||el.querySelector('time,.date,.posted,[class*="date"],[class*="time"]')?.innerText||'');
   let text=norm((el.querySelector('.post_body,.post-content,.content,.message-content,[class*="body"]')||el).innerText);
   posts.push({post_id:id, author, datetime_raw:dt, datetime_iso:null, text, links:links(el), short_summary:''});
 }
 const article={title:document.title, text:norm(document.querySelector('article,main')?.innerText||document.body?.innerText||''), links:links(document)};
 const tables=Array.from(document.querySelectorAll('table')).slice(0,20).map(t=>Array.from(t.rows).map(r=>Array.from(r.cells).map(c=>norm(c.innerText))));
 const search_results=Array.from(document.querySelectorAll('a[href]')).filter(a=>norm(a.innerText).length>3).slice(0,50).map(a=>({title:norm(a.innerText), url:a.href, snippet:norm(a.closest('li,article,div')?.innerText||'').slice(0,500)}));
 return {url:location.href,title:document.title, adapter:is4pda?'4pda':'generic_forum', confidence:is4pda?0.85:(posts.length?0.55:0.2), posts, article, tables, search_results};
})()
"""
    data = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script, timeout=timeout_from(args))
    if not isinstance(data, dict):
        raise ToolError("extractor returned an unexpected payload")
    return data


def _write(root: Path, paths: dict[str, Path], prefix: str, payload: Any) -> tuple[str, dict[str, Any]]:
    f = write_json_artifact(root, paths, prefix, payload)
    meta = metadata(paths); meta.update({"artifact_file": str(f), "artifact_id_hint": "use list_artifacts then read_artifact_by_id/search_artifact", "goal_status": "answer_ready"})
    return f"{prefix}_ok=true\nartifact_file: {f}\ncount: {len(payload) if isinstance(payload, list) else ''}\n" + cap_output(json.dumps(payload, ensure_ascii=False, indent=2), 5000), meta


def action_extract_forum_posts(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = _page_payload(args); requested = str(args.get("adapter") or "auto")
    adapter = data.get("adapter") if requested in {"auto", "4pda", "generic_forum"} and (requested == "auto" or requested == data.get("adapter")) else "generic_forum"
    posts = data.get("posts") if isinstance(data.get("posts"), list) else []
    for p in posts:
        p["datetime_iso"] = normalize_timestamp(p.get("datetime_raw"))
        p["short_summary"] = short_summary(str(p.get("text") or ""))
    payload = {"adapter": adapter, "confidence": data.get("confidence", 0.0), "goal_status": "extracted", "posts": posts}
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
