# Manual Challenge

Use for Cloudflare, captcha, or manual confirmation pages.

```text
action=challenge_detected profile=example url=https://example.com/protected
```

If manual work is required:

1. Send the returned manual URL/passcode to the user.
2. Wait for the user to reply that the check is done.
3. Call:

```text
action=continue_after_manual profile=example url=https://example.com/protected
```

4. Continue with `desktop_snapshot` or `desktop_open` on the same profile.
