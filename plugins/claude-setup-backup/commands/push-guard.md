---
description: Install, remove or list the git pre-push hook that blocks a push containing your personal terms
argument-hint: "install [REPO] | remove [REPO] | status"
allowed-tools: Bash(python3:*), Bash(gh repo view:*)
---

Run this with the Bash tool and show the user its output:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" guard $ARGUMENTS
```

The repo defaults to the current directory. Notes for the user:

- The guard checks every file in the pushed commit and every new commit
  message against `~/.claude/personal-terms.txt`, and blocks the push on a
  match. It fails closed: if the list is missing, the push is blocked too.
- It belongs on repos that are **public or will be**. Don't put it on the
  private backup repo, which is supposed to hold personal detail. If they ask
  which repos to guard, check visibility with `gh repo view OWNER/NAME --json
  visibility` and suggest the public ones.
- If install refuses because the repo already has a pre-push hook, show them
  the one line the error gives to add to their existing hook. Don't overwrite
  it.
- When a push is blocked: the fix is to amend the commit that added the term
  (or rewrite the branch). A new commit removing it still publishes the old
  one. For a false alarm, add an exception with
  `/claude-setup-backup:personal-terms add` using `--allow`, or push once with
  `git push --no-verify`.
