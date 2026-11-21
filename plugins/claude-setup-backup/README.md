# claude-setup-backup

**Back up your Claude Code setup to a private git repo, and rebuild a new or
wiped machine from it in one command.**

Claude Code keeps what makes it *yours* in a handful of places: `CLAUDE.md` and
the files it imports, a memory folder per project, your slash commands, agents
and skills, and the hooks in `settings.json`. None of it is backed up by
default. Lose the disk, and you're starting from a blank assistant.

This plugin backs all of that up and puts it back, on the same machine or a
different one, Linux, macOS or Windows.

```
/plugin marketplace add brackettmj/claude-skills
/plugin install claude-setup-backup@brackettmj-skills
/claude-setup-backup:setup
```

## What it backs up

| | |
|---|---|
| `~/.claude/CLAUDE.md` | and every file it `@`-imports, followed recursively |
| Memory | every project's memory folder, including new projects as they appear |
| `commands/`, `agents/`, `skills/`, `output-styles/` | whatever you have in `~/.claude` |
| `settings.json` | hooks and status line. **Env values are blanked**; only the names are kept |
| Extras | any other file or folder under your home folder that you name |

It never backs up secret values, `~/.claude.json` (your account and MCP
servers), or session transcripts.

## Commands

| Command | What it does |
|---|---|
| `/claude-setup-backup:setup` | Scans this machine and shows what it found. You untick anything to leave out, pick a private repo, and say whether to sync automatically. Your files stay where they are; the repo holds copies. |
| `/claude-setup-backup:sync` | Syncs both ways. `--dry-run` shows what would change and writes nothing. |
| `/claude-setup-backup:restore owner/repo` | Rebuilds a machine from the backup. Previews first. Never overwrites a file that's already there. |
| `/claude-setup-backup:personal-terms` | Builds your list of terms that must never be published. Claude suggests them from your CLAUDE.md and memory; you approve each one. `check FILE` scans a post or doc. |
| `/claude-setup-backup:push-guard install` | Adds a pre-push hook to a repo that blocks any push containing one of your terms. |
| `/claude-setup-backup:doctor` | Checks the setup is whole: CLAUDE.md imports resolve, memory index links point at real files, backed-up hooks are wired, listed repos are cloned, the backup is private and current. |

If you turn on auto-sync during setup, it syncs at the start and end of every
session. Off by default.

## How it handles the hard parts

**Memory follows the project, not the path.** Claude Code names each memory
folder after the project's full path, so the same project is
`-srv-alex-proj` on one machine and `D--people-alex-proj` on another. The
backup stores it under a name with your home folder stripped off (`proj`), and
restore rebuilds the right folder name for the new machine.

**Deletions stick.** A plain two-way copy can't tell "deleted here" from "new
over there," so deleted files come back from the other machine. This one
remembers what each machine had at its last sync, so it knows the difference.
A file deleted on another machine is moved to
`~/.claude/claude-setup-backup-trash/<date>/`, not destroyed.

**Both sides changed? You get both.** Your copy stays, and the backup's
version is saved beside it as `<name>.from-backup`.

**It refuses public repos.** Memory holds personal detail. Before setup and
before every push, it asks GitHub whether the repo is private, and stops if
it isn't, including a repo that was private at setup and got flipped public
later. For a non-GitHub remote it can't check, it needs
`--allow-unverified`.

**It refuses to push keys.** Before anything leaves the machine, it scans
outgoing files for Anthropic, OpenAI, OpenRouter, AWS, GitHub, Slack and
Google key shapes and for private key blocks. One hit stops the whole sync,
and the error names the file and line without repeating the key.

**A missing import gets flagged.** If `CLAUDE.md` imports a file that doesn't
exist, Claude Code skips it with no warning, and everything in it is missing
from your sessions. `doctor` makes that a `FAIL`. This plugin exists because a
one-letter typo in an import did exactly that.

## Keeping personal detail out of what you publish

The backup is private and is supposed to hold personal detail. Public repos
aren't. So the plugin also keeps a **personal-terms list**: your name, your
employer, people you mention, your assistant's persona name, hostnames, your
home network range. It also has a **push guard**, a git pre-push hook that
blocks a push carrying any of them.

- The list starts empty. The first session after install creates
  `~/.claude/personal-terms.txt` with comments only. Nothing ships with the plugin.
- `/claude-setup-backup:personal-terms` has Claude read your CLAUDE.md and
  memory and **suggest** terms. You approve each one; nothing is added without a yes.
- `/claude-setup-backup:push-guard install` puts the hook on a repo. It checks
  every file in the pushed commit and every new commit message. If the list is
  missing, it blocks rather than letting the push through unchecked.
- Exceptions (a public author credit) are lines starting with `!`.
- `personal-terms check FILE` checks anything you publish outside git: a
  post, a doc, an email draft.
- The list travels in your private backup, and `REBUILD.md` lists the repos
  to put the guard back on.

## The rebuild checklist

Every sync writes `REBUILD.md` into the backup repo. It's built from your
backup: the restore command for your repo, the git repos to re-clone, the
env variable names to fill in, and the tools your hooks call. When a machine
dies, that file is the whole plan.

## Requirements

- Python 3.9 or newer (standard library only) and git.
- The GitHub CLI (`gh`), signed in, for a GitHub backup. It's how the privacy
  check works.
- The session hooks call `python3`. On Windows, if only `python` or `py` is
  on your PATH, auto-sync won't run; the slash commands still work.

## Limits

- Memory for a project outside your home folder only restores onto a machine
  with the same folder layout. Setup leaves these out by default.
- Claude Code shortens very long project folder names with a hash. Those may
  not map across machines whose home folders differ in length.
- `restore` writes `settings.json` only if the machine doesn't have one. If it
  does, `doctor` lists the backed-up hooks it's missing.

## Tests

```
python3 -m unittest discover plugins/claude-setup-backup/tests
```

Each guard is tested from both sides, the clean case passing and a planted
defect caught: a public repo, a repo made public later, a key in a memory file
and one in `settings.json`, a broken import, a dead memory link, a missing
hook, a deletion that must stay deleted, a dry run that must write
nothing, and pushes with a term in a file, in a commit message, with an
exception, and with the list missing. Every guard was also broken on purpose
to confirm a test goes red.

MIT licensed.
