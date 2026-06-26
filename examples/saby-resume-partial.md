# Saby Resume Partial

Use when the previous Saby export returned a partial CSV.

If the previous result said `collection_complete=false`, send the partial CSV first and ask the user whether to continue.

If the user confirms, make one more pass:

```text
action=saby_tenders_csv profile=saby mode=yesterday resume_state=true
```

Keep the same `target_date` or `filter_text` if they were used before.
