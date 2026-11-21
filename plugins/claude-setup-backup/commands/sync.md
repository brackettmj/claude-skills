---
description: Sync this machine's Claude Code setup with its backup repo, both ways
allowed-tools: Bash(python3:*)
---

Run this with the Bash tool and show the user its output:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" sync $ARGUMENTS
```

`$ARGUMENTS` may be `--dry-run` (show what would change, write nothing) or
`-m "message"`.

Then, in a sentence or two: what came in from the backup, what went out, and
any deletions carried over. If there was a conflict, name the file. Their copy
was kept, and the backup's version sits beside it with a `.from-backup` suffix
for them to compare. If the sync refused because of a key or a public repo,
explain the fix the error gives. Never work around it.
