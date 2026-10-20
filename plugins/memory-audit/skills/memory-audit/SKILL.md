---
name: memory-audit
description: Use when the user asks to audit, check, review or clean up Claude's memory, or asks whether saved memories are stale, duplicated, orphaned or broken. Runs a read-only checker over a Claude Code memory folder (MEMORY.md plus one file per memory), then judges the cases a script can't. Reports and recommends; never deletes or edits a memory itself.
---

# Memory audit

Claude Code's memory folder drifts. Memories get dropped from the index but stay
on disk, links point at names that changed, and a memory that copies a file
quietly goes stale while the file moves on. This skill finds those, explains each
one, and leaves every change to the user.

## 1. Find the folder

It's usually `~/.claude/projects/<project>/memory/`, holding `MEMORY.md` and one
`.md` file per memory. If the session's instructions name a memory folder, use
that one. If several projects have one and it's unclear which, list them and ask.

## 2. Run the checker

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/memory-audit/scripts/memory_audit.py" MEMORY_DIR
```

It reads files and prints findings. It never writes. Exit 1 means at least one
error.

## 3. Judge what the script can't

- **may-duplicate.** Read the memory and the file it names. If the file already
  records what the memory says, the memory is a second copy that will drift, so
  recommend retiring it. If the memory holds something the file doesn't (why a
  choice was made, a preference, a gotcha), it earns its place. Say which, in one
  line, with the fact that decided it.
- **missing-path.** A path that doesn't exist *here* may exist on another machine
  (a server, a second laptop). If the memory says where the path lives, say so
  rather than calling it stale.
- **orphan.** Two fixes, and they're opposites: add it back to `MEMORY.md`, or
  delete the file. Dropping it from the index doesn't remove it, because Claude
  can still recall it. Before recommending a delete, check that what it says is
  recorded somewhere else, or no longer true.
- **dangling-link.** Often deliberate: a link can mark a memory worth writing
  later. When the checker suggests a near match (`feedback_x` for `feedback-x`),
  it's almost certainly a typo.

## 4. Report

Lead with the count and the one thing most worth fixing. Then group the findings:
fix now (errors), worth a look (warnings, plus may-duplicate pairs you judged as
real copies), and fine as is (notes you checked and cleared). Give each fix as the
exact change: the line to add to `MEMORY.md`, the link to rename, the file to
delete.

**Don't make the changes.** The user decides what to delete. Offer to apply the
fixes they pick, and apply only those.
