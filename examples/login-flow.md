# Login Flow

Use for a persistent authenticated session.

```text
action=login profile=github url=https://github.com/login
```

Then:

1. Send `manual_desktop_url` and `vnc_passcode` to the user.
2. Wait for the user to finish login manually.
3. Call:

```text
action=continue_after_manual profile=github url=https://github.com/
```

4. Continue later browser work with the same `profile=github`.
