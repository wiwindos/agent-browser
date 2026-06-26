# Saby Export

Use the built-in Saby export flow instead of pasting long page-console scripts.

Required profile:

- Always use `profile=saby`.

Recommended flow:

1. Start or reuse the desktop session with `desktop_open profile=saby url=https://trade.saby.ru/page/tenders-all?...`.
2. Call `saby_tenders_csv profile=saby`.
3. Send the returned CSV path with `send_file`.

Subscription/sidebar flow:

```text
action=desktop_open profile=saby url=https://trade.saby.ru/page/tenders-subscriptions
action=saby_tenders_csv profile=saby mode=yesterday subscription_text=БПЛА
```

Use `subscription_text` when the left-menu item is known. The collector selects that item through in-page CDP before collection, which avoids slow manual sidebar clicks.

One-call preparation is allowed:

```text
action=saby_tenders_csv profile=saby url=https://trade.saby.ru/page/tenders-all?... mode=yesterday reset_state=true
```

Prepared flow:

- In a fresh sandbox this call can return `prepared_for_collection=true`.
- When that happens, call `saby_tenders_csv` again with the same `profile`, `mode`, and optional `target_date` or `filter_text`.
- The second call should normally use `resume_state=true` and omit `url`.

Partial and resume policy:

- If `collection_complete=false`, the CSV is partial.
- Send the partial CSV honestly.
- Stop after sending it and ask the user whether to continue.
- If the user confirms, make one more `saby_tenders_csv` call with the same `profile`, `mode`, filters, and `resume_state=true`.
- Do not chain multiple long resume passes in one reply.

Useful options:

- `mode=yesterday`: collect yesterday's tenders.
- `mode=visible`: export only visible rows.
- `target_date=YYYY-MM-DD`: override the target date.
- `filter_text=...`: keep only rows whose visible text matches the filter.
- `subscription_text=...`: select a Saby subscriptions/sidebar item before collection, e.g. `БПЛА`.
- `delay_after_click=...`: tune paging delay; default is 350ms.
- `row_change_timeout_ms=...`: tune row-change wait after paging/sidebar selection; default is 2500ms.
- `reset_state=true`: start a fresh run.
- `keep_manual_browser=true`: keep the manual browser lease after a complete export.

Completion semantics:

- Completion means the collector observed the target date and then a normal older/stable stopping condition.
- It is an operational stopping condition, not a legal guarantee that the website exposed every possible row.
