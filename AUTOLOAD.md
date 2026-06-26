Use this skill only for explicit browser automation, live site interaction, Saby/SBIS export, UI testing, login flows, manual desktop/noVNC, or protected browser artifacts.
First tool: `skill_agent-browser_browser`.
Preferred starts:
- Generic site task: `action=open`, then `action=snapshot`.
- Saby/SBIS: `profile=saby`, then `action=desktop_open` or `action=saby_tenders_csv`.
- Saby subscription export: prefer `action=saby_tenders_csv profile=saby subscription_text=<left menu text> mode=yesterday`; do not manually click the sidebar if the text is known.
- Existing browser artifact path: `action=read_artifact`.
Snapshot artifact rule:
- When a browser action returns `snapshot_file`, `state_file`, `text_file`, or any `*_file`, pass that exact file path to `action=read_artifact`.
- Never pass an artifact run directory like `browser-artifacts/<site>/<timestamp>/` to `read_artifact`.
Empty snapshot fallback:
- If `snapshot_ok=true` but `refs_count=0`, `title=(unknown)`, or useful page text is missing, first call `action=read_artifact` on the exact returned `snapshot_file`.
- If the artifact is still unusable, switch to `action=desktop_open` with the same `profile`/`url`, then `action=desktop_snapshot`.
- Do not call `screenshot` just to recover from an empty snapshot unless the user explicitly asked for an image or diagnostics.
Hard rules:
- Do not use shell commands for browser work.
- Do not use `read_file` on `browser-artifacts/`; use `read_artifact`.
- If tool output already contains `next_step:` or `next_tool_call`, follow it directly.
