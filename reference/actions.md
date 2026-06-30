# Actions

Core actions:

- `start`: runtime check or bootstrap.
- `skills`: load upstream browser instructions.
- `open`: open a URL and wait for load.
- `snapshot`: return an accessibility snapshot with refs.
- `click`: click a ref or selector.
- `fill` / `type`: enter text into inputs.
- `wait`: wait for text, selector, URL, milliseconds, or load state.
- `screenshot`: save a PNG under the active artifact directory.

Manual desktop actions:

- `manual_desktop`: start classic noVNC/manual desktop and return URL plus passcode.
- `desktop_open`: navigate the already-running desktop Chrome through CDP; starts manual desktop if needed.
- `desktop_snapshot`: return URL, title, and visible text from desktop Chrome.
- `desktop_screenshot`: save a screenshot from desktop Chrome.
- `page_markdown` / `page_markdown.get`: extract the current desktop Chrome page as Markdown with stable `node_id` values and a revisioned action map.
- `read_page_md`: read the latest Markdown page artifact.
- `page_markdown.act`: perform `click`, `fill`, `type`, `select`, or `submit` against a Markdown `node_id`, wait/settle, then return the refreshed `action_page_markdown` in the same response. Pass `node_action` (or `operation`/`act`), `node_id`, optional `revision`, and `text`/`value` for input actions.
- `click_handle` / `fill_handle` / `select_handle`: legacy handle actions retained for compatibility; prefer `page_markdown.act` for new Markdown-first workflows.
- `evaluate`: run JavaScript in desktop Chrome through CDP.
- `stop_desktop`: stop manual desktop processes.
- `close_manual_access`: close public noVNC/VNC access while keeping the internal Chrome session alive.
- `share_session`: expose the agent-browser dashboard, not classic noVNC.

Auth and recovery actions:

- `login`: open a site with a persistent profile.
- `clear_session`: delete the saved session for the target profile/site.
- `challenge_detected`: prepare a manual challenge handoff.
- `continue_after_manual`: verify that the manual challenge is complete and preserve the session.
- `close`: close the daemon and clear stale locks.
- `recover`: close the daemon, clear stale locks, and optionally reinstall dependencies.

Artifacts and admin actions:

- `downloads`: list or wait for files in skill-managed download directories.
- `status`: inspect local profiles, artifacts, and lock state.
- `profile_aliases`: list auth/profile alias groups.
- `set_profile_alias`: define a named alias group for product and SSO domains.
- `cleanup`: delete old artifacts while preserving saved profiles.

Domain action:

- `saby_tenders_csv`: collect Saby Trade tender rows into a CSV inside the active artifact download directory.
