---
description: Build or check your list of personal terms (name, employer, people, hostnames) that must never be published
argument-hint: "[suggest | add TERM | check FILE]"
allowed-tools: Bash(python3:*), Read
---

The list lives at `~/.claude/personal-terms.txt`. It's created empty (comments
only) the first time a session starts after this plugin is installed. It is
the user's own: nothing in it ships with the plugin.

What to do depends on `$ARGUMENTS`:

**`suggest`, or nothing given:** propose terms for the user to approve.
1. Read `~/.claude/CLAUDE.md`, the files it imports, and the `MEMORY.md` index
   of each project memory folder (open individual memories only if the index
   is too thin to tell).
2. Propose terms that would identify the user or the people and places around
   them if they showed up in something public: their full name and handle
   variants, their employer and internal project or team names, names of
   people they mention, their assistant's persona name if it has one, machine
   hostnames, their home network range, private domains.
   Leave out generic words that would match everyday text (a common first
   name on its own, a big company's name that appears in product names); say
   which ones you left out and why.
3. Ask the user to approve each term, one question per term or a short
   multi-select. Never add a term they didn't approve. Ask whether anything
   that names them is *meant* to be public, such as an author credit; those
   become exceptions.
4. Add the approved terms. Use `--literal` for plain text:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" terms add --literal "Term one" "Term two"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/csb.py" terms add --allow "Their Name (MIT)"
   ```

   Don't repeat the full list back in chat once it's saved. Say how many terms
   were added and where the file is.

**`add ...`:** run `terms add --literal` with the given text.

**`check PATH`:** run `terms check PATH` and report any hits. Use this for
anything published outside git: a post, a doc, an email draft.

Then suggest `/claude-setup-backup:push-guard install` for the repos they
publish from, if they haven't.
