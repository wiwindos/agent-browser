# Manual Desktop And noVNC

Use `manual_desktop` when the user explicitly wants classic noVNC/manual desktop access or when a site requires human interaction.

What it returns:

- `manual_desktop_url`
- `vnc_passcode`

Normal manual workflow:

1. Start `manual_desktop` or `desktop_open` with the target `profile` and optional `url`.
2. Send the returned URL and passcode to the user.
3. Wait for the user to finish manual work.
4. Continue with `desktop_snapshot`, `desktop_open`, `desktop_screenshot`, or `continue_after_manual`.

Challenge workflow:

1. Call `challenge_detected`.
2. If it says the page is already clear, continue automation and do not ask for manual action.
3. If manual work is required, send the handoff URL/passcode.
4. Wait for the user to confirm that the check is done in any wording.
5. Call `continue_after_manual` with the same `profile` and `url`.

Lease rules:

- The manual desktop resource is single-profile inside one sandbox.
- Same-profile CDP automation is allowed after manual desktop starts.
- Cross-profile manual requests can return `manual_browser_busy=true`.
- Do not interrupt another profile's manual desktop unless the user explicitly asks for interruption.

Dashboard note:

- `share_session` exposes the agent-browser dashboard.
- `manual_desktop` exposes classic noVNC.
- For captcha and Cloudflare flows, prefer `manual_desktop`.

