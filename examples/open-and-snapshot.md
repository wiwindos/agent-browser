# Open And Snapshot

Use for a normal page inspection.

```text
action=open url=https://example.com
action=snapshot
action=screenshot path=screenshots/home.png
```

Expected pattern:

- Open the page.
- Read refs from the snapshot.
- Use `click` or `fill` against refs for follow-up work.
