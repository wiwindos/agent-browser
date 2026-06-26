# Auth And Profiles

Use persistent browser profiles instead of asking the user for secrets in chat.

Profile rules:

- Prefer an explicit `profile` for authenticated work.
- Reuse the same `profile` across the full login and follow-up workflow.
- If both `profile` and `site_key` are provided, `profile` wins.
- Follow-up actions may omit `profile` when they continue the same active session, but explicit reuse is still preferred.

Storage:

```text
.agent-browser/profiles/<profile>/
```

Saby rules:

- Always use `profile=saby` for `saby.ru`, `sso.saby.ru`, and `trade.saby.ru`.
- Do not split Saby across different host-based profile names.

Alias groups:

- Use `set_profile_alias` when one product spans unrelated product and SSO domains.
- Aliases are stored per user in `.agent-browser/profile-aliases.json`.

Recommended login flow:

1. Call `login` with the target `url` and stable `profile`.
2. Send `manual_desktop_url` and `vnc_passcode` to the user.
3. The user enters login, password, captcha, and OTP manually in noVNC.
4. After the user replies that login is complete, call `continue_after_manual` with the same `profile` and `url`.
5. Reuse that same profile for later authenticated tasks.

Never ask the user to paste passwords, OTPs, recovery codes, or bearer tokens into chat.
