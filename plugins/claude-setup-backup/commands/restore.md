---
description: Rebuild this machine's Claude Code setup from a claude-setup-backup repo
argument-hint: OWNER/NAME
allowed-tools: Bash(python3:*), Bash(git clone:*)
---

Restore the user's setup from their backup repo `$ARGUMENTS`. If no repo was
given, ask for it (`owner/name`).

1. Preview first, and show the user the result:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" restore --remote $ARGUMENTS --dry-run
   ```

2. Once they say go, run it for real without `--dry-run`. Files already on
   this machine are never overwritten: where both sides differ, their copy is
   kept and the backup's version is saved beside it as `.from-backup`.

3. Read `REBUILD.md` in the backup folder the script names. Offer to clone each
   repo it lists (one `git clone` per repo, after they agree). List the env
   variable names they need to set in `~/.claude/settings.json` and the tools
   their hooks call, because those can't come from a backup.

4. Run `/claude-setup-backup:doctor` and go through anything that isn't `ok`.
