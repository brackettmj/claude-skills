---
description: Check that the bash gate is installed and live, and print the verify script's path for use in run scripts
allowed-tools: Bash(bash:*)
---

Run exactly this with the Bash tool, with nothing added to it, and show the user
its output:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh" $ARGUMENTS
```

Each line of output starts with `ok`, `FAIL` or `INCONCLUSIVE`, which is the
result. Then tell the user, in two or three sentences:

- whether the gate is live (every line `ok`), broken (a `FAIL` line, so don't
  give an unattended run a Bash tool until it's fixed), or inconclusive (`--live`
  proved nothing and is worth one more try)
- the absolute path of `verify.sh`, so they can call it from the script that
  starts their unattended runs. This session already knows it as
  `${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh`; print it expanded.
- if they ran it without `--live`: that only checked the gate script. Running
  `/bash-gate:verify --live` checks that Claude Code really blocks a command,
  using one short headless session.
