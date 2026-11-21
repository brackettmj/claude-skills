---
description: Check that this machine's Claude Code setup is whole and matches its backup
allowed-tools: Bash(python3:*)
---

Run this with the Bash tool and show the user its output:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" doctor
```

Each line starts with `ok`, `FAIL` or `warn`. Then give the user the fix for
each `FAIL`, most important first. A broken CLAUDE.md import comes first: Claude
Code skips a missing import without any warning, so everything in that file is
silently missing from their sessions. If every line is `ok`, say so in one
sentence.
