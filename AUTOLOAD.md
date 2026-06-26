Use this skill only for explicit browser automation, live site interaction, Saby/SBIS export, UI testing, login flows, manual desktop/noVNC, or protected browser artifacts.
First tool: `skill_agent-browser_browser`.
Preferred starts:
- Generic site task: `action=open`, then `action=snapshot`.
- Saby/SBIS: `profile=saby`, then `action=desktop_open` or `action=saby_tenders_csv`.
- Existing browser artifact path: `action=read_artifact`.
Hard rules:
- Do not use shell commands for browser work.
- Do not use `read_file` on `browser-artifacts/`; use `read_artifact`.
- If tool output already contains `next_step:` or `next_tool_call`, follow it directly.
