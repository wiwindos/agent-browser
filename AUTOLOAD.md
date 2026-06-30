Use this skill only for explicit browser automation, live site interaction, Saby/SBIS export, UI testing, login flows, manual desktop/noVNC, or protected browser artifacts.
First tool: `skill_agent-browser_browser`.
Primary universal workflow:
- Start interactive tasks with `action=desktop_open` (or `open` -> `wait_ready` for simple pages), then call `action=page_markdown`.
- Read the Markdown with `action=read_page_md` when prompted; reason over page content and UI `node_id` values yourself.
- Choose the needed `node_id` and call `action=page_markdown.act node_id=<id> node_action=click|fill|type|select|submit revision=<revision>`.
- Use the refreshed `action_page_markdown` returned by `page_markdown.act` as the next state, and repeat until solved.
- This is the main workflow for catalogs, forums, search pages, tables, personal accounts, SPAs, and “next/show more/load more” controls.
- Specialized extractors (`extract_table`, `extract_search_results`, `extract_updates_by_date`, `extract_forum_posts`, etc.) are optional fast paths only after Markdown inspection shows they fit; do not make them the primary workflow.
Fast starts:
- Saby/SBIS: `profile=saby`, then `action=desktop_open` or `action=saby_tenders_csv`.
- Saby subscription export: prefer `action=saby_tenders_csv profile=saby subscription_text=<left menu text> mode=yesterday`; do not manually click the sidebar if the text is known.
- Existing browser artifact path: `action=read_artifact`.
- Manual confirmation follow-up after a browser handoff: call `continue_after_manual` on the same `profile` and `url`.
Artifact and empty snapshot rules:
- When a browser action returns `snapshot_file`, `state_file`, `text_file`, `markdown_file`, `page_markdown_file`, or any `*_file`, pass that exact file path to the appropriate artifact reader (`read_page_md` for Markdown, otherwise `read_artifact`).
- If tool metadata contains `required_next_tool_call`, execute it before any fallback unless the user changes the task or a challenge is visible.
- If `snapshot_ok=true` but `refs_count=0`, `title=(unknown)`, or useful page text is missing, first call `read_artifact` on the exact returned `snapshot_file`; if still unusable, switch to `desktop_open`, then `page_markdown`.
Hard rules:
- Do not use shell commands for browser work.
- Do not use `read_file` on `browser-artifacts/`; use `read_artifact`/`read_page_md`.
- If tool output already contains `next_step:` or `next_tool_call`, follow it directly.
- Do not use screenshots, `read_file`, `run_command`, raw `fetch_page`, large raw `evaluate`, or `action=run` as substitutes for extracting page text or deciding node actions.
