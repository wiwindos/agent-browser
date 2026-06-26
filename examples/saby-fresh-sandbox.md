# Saby Fresh Sandbox

Use when Saby export must also start the desktop in a fresh sandbox.

```text
action=saby_tenders_csv profile=saby url=https://trade.saby.ru/page/tenders-all?... mode=yesterday reset_state=true
```

If the result says `prepared_for_collection=true`:

```text
action=saby_tenders_csv profile=saby mode=yesterday resume_state=true
```

Then send the returned CSV path with `send_file`.
