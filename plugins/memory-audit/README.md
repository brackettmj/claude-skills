# memory-audit

Checks a Claude Code memory folder for the ways it drifts, then has Claude judge
the cases a script can't. **Reports only.** It never deletes or edits a memory;
you pick the fixes.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install memory-audit@brackettmj-skills
```

Then ask: *"audit my memory"* or *"are any of my saved memories stale?"*

## What it finds

| Code | Severity | What it means |
|---|---|---|
| `orphan` | error | A memory file `MEMORY.md` doesn't list. Claude can still recall it, so it goes stale where nobody reviews it. Removing a line from the index doesn't delete the memory. |
| `dead-index` | error | An index line linking to a file that isn't there. |
| `frontmatter` | error | No frontmatter, or no `name`, `description` or `type`. |
| `bad-type` | error | A type other than `user`, `feedback`, `project` or `reference`. |
| `duplicate-name` | error | Two files share a name slug, so links to it are ambiguous. |
| `name-format` | warning | A name that isn't lowercase-kebab-case. |
| `missing-path` | warning | The memory names a file or folder that doesn't exist on this machine. |
| `index-length` | warning | `MEMORY.md` runs past the 200 lines Claude Code loads. |
| `dangling-link` | note | A `[[link]]` to a name no memory has. Suggests the near match when it's a likely typo. |
| `may-duplicate` | note | A project memory names a file that exists. Claude reads both and says whether the memory is just a second copy. |

The judgment calls are in step 3 of the [skill](skills/memory-audit/SKILL.md):
whether a memory copies its file, whether a missing path lives on another
machine, and whether an orphan should go back in the index or be deleted.

## Run it without Claude

```bash
python3 skills/memory-audit/scripts/memory_audit.py ~/.claude/projects/<project>/memory
python3 skills/memory-audit/scripts/memory_audit.py <dir> --json
```

Exit 0 means no errors, 1 means at least one error, 2 means the folder couldn't
be read. Standard library only.

## Tests

```bash
python3 -m unittest discover plugins/memory-audit/tests
```

18 tests. Each starts from a clean folder that must produce no findings, plants
one defect, and checks that exactly that defect comes back. Breaking any single
check in the script turns at least one test red.
