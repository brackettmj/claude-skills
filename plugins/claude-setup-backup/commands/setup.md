---
description: Back up this machine's Claude Code setup (CLAUDE.md, memories, commands, hooks) to a private git repo
allowed-tools: Bash(python3:*), Bash(gh api user:*), Write
---

Set up a backup of the user's Claude Code setup. Nothing gets moved: their files
stay where they are, and the backup repo holds copies.

1. Run this with the Bash tool and save its output to a temporary file:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" scan --json
   ```

2. Show the user what was found as a table: CLAUDE.md, each file it imports,
   each folder under `dirs`, each memory folder (key, file count, the project
   path it belongs to), `settings.json` (hook count, env key names), and the git
   repos found behind memory folders. Every item says whether it's included.
   Call out problems plainly:
   - `imports_missing`: CLAUDE.md imports a file that doesn't exist. Claude
     Code skips it without a warning. Tell them before they back it up.
   - `imports_outside_home`: these can't be backed up.
   - a big folder under `dirs` (check `bytes`): often skills installed from
     somewhere else, which can simply be reinstalled. Ask whether to include it.
   - memory folders with `include: false`: they belong to projects outside the
     home folder and only restore onto a machine with the same layout.

3. Ask the user, one question at a time:
   - Anything to leave out? Set `include` to false on those items.
   - Which private GitHub repo should hold the backup? Suggest
     `<their GitHub username>/claude-setup-backup` (`gh api user -q .login`).
     If it doesn't exist, offer to create it as private.
   - Any other files or folders under their home folder to include (a
     notes file, a scripts folder)? Add each as a home-relative path to `extra`.
   - Should it sync automatically at the start and end of every session?

4. Write the edited JSON back to the temp file and run:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" init --remote OWNER/NAME --select FILE [--create] [--auto-sync]
   ```

   Never add `--allow-unverified` unless the user says the remote is private
   and isn't on GitHub. The script refuses public repos on purpose, because
   memory holds personal detail. Don't look for a way around that.

5. Report what was backed up, the repo it went to, and that the repo now has a
   `REBUILD.md` with the steps for a new machine.

6. Offer the push guard: "Do you publish anything (public repos, a site)? I can
   build a list of personal terms that must never be published, and block any
   git push that contains one." If yes, follow
   `/claude-setup-backup:personal-terms` (suggest mode), then
   `/claude-setup-backup:push-guard install` on each repo they name.

7. Suggest running `/claude-setup-backup:doctor`.
