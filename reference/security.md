# Security

Safety boundaries:

- All browser work must stay inside the current per-user sandbox.
- All paths must remain inside the current workspace-managed directories.
- Do not browse through raw shell commands.
- Do not install arbitrary browser tooling from user-provided URLs.
- Do not expose dashboard or noVNC URLs unless the current session is trusted and the workflow requires manual access.

Secret handling:

- Never ask for passwords, OTPs, recovery codes, bearer tokens, or API keys in chat.
- Do not copy secrets into logs, reports, screenshots, or memory.
- Use persistent browser profiles for website sessions instead of storing plaintext credentials.

Manual challenge policy:

- Human-assisted challenge completion is allowed.
- Automated bypass of captcha or Cloudflare is not.

File safety:

- Use skill-managed artifacts and downloads only.
- Preserve `.agent-browser/profiles/` during cleanup unless the explicit task is session reset.
