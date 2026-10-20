#!/usr/bin/env python3
"""Audit a Claude Code memory directory. Reports only; never changes a file.

Usage:
    memory_audit.py MEMORY_DIR [--json]

MEMORY_DIR is the folder holding MEMORY.md and one .md file per memory, usually
~/.claude/projects/<project>/memory/.

Exit 0 when there are no errors (warnings and notes may remain), 1 when there is
at least one error, 2 when the directory can't be read.

What it checks, and why each one matters:

  orphan          A memory file the index doesn't list. Claude can still recall
                  it, so it goes stale where nobody reviews it. Dropping a memory
                  from MEMORY.md is not the same as deleting it.
  dead-index      An index line that links to a file that isn't there.
  frontmatter     Missing or unreadable frontmatter, or a missing name,
                  description or type.
  bad-type        A type other than user, feedback, project or reference.
  duplicate-name  Two files with the same name slug. Links to it are ambiguous.
  name-format     A name that isn't a lowercase-kebab-case slug.
  missing-path    The body names a file or folder that no longer exists. The
                  memory was true when written; this one may not be any more.
  index-length    MEMORY.md is longer than the part Claude Code loads.
  dangling-link   A [[link]] to a name no memory has. Often fine (it can mark
                  something worth writing later), so it's a note, not an error.
  may-duplicate   A project memory that names a file which exists. If that file
                  already records the fact, the memory is a second copy that will
                  drift. The script can't judge that; it lists the pair to read.
"""

import json
import os
import re
import sys

TYPES = {"user", "feedback", "project", "reference"}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
INDEX_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+\.md)\)")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
# A path in backticks that starts at ~ or /. Placeholders (<x>, *, $VAR, {x})
# are skipped, because they name a pattern, not a file.
BACKTICK_PATH = re.compile(r"`((?:~|/)[^`\s]*)`")
PLACEHOLDER = re.compile(r"[<>*${}]")
# Code spans and fenced blocks, removed before looking for [[links]], so a bash
# test like `[[ -f x ]]` isn't read as one.
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
# Claude Code loads the first 200 lines of MEMORY.md into each session.
INDEX_LOAD_LINES = 200

SEVERITY = {
    "orphan": "error", "dead-index": "error", "frontmatter": "error",
    "bad-type": "error", "duplicate-name": "error",
    "name-format": "warning", "missing-path": "warning", "index-length": "warning",
    "dangling-link": "note", "may-duplicate": "note",
}


def parse_frontmatter(text):
    """Return (fields, body). Fields holds top-level keys plus metadata.* keys
    flattened, which is all this audit needs. None if there is no frontmatter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None, text
    fields, parent = {}, None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        indent, key, value = m.groups()
        value = value.strip().strip('"').strip("'")
        if indent and parent:
            fields[f"{parent}.{key}"] = value
        else:
            parent = key if not value else None
            fields[key] = value
    return fields, "\n".join(lines[end + 1:])


def audit(memdir):
    findings = []

    def add(code, file, detail):
        findings.append({"code": code, "severity": SEVERITY[code], "file": file, "detail": detail})

    index_path = os.path.join(memdir, "MEMORY.md")
    files = sorted(f for f in os.listdir(memdir) if f.endswith(".md") and f != "MEMORY.md")

    indexed = set()
    if os.path.isfile(index_path):
        with open(index_path, encoding="utf-8") as fh:
            index_lines = fh.read().split("\n")
        if index_lines and index_lines[-1] == "":
            index_lines.pop()
        for n, line in enumerate(index_lines, 1):
            for target in INDEX_LINK.findall(line):
                if "://" in target:
                    continue
                indexed.add(os.path.normpath(target))
                if not os.path.isfile(os.path.join(memdir, target)):
                    add("dead-index", "MEMORY.md", f"line {n} links to {target}, which doesn't exist")
        if len(index_lines) > INDEX_LOAD_LINES:
            add("index-length", "MEMORY.md",
                f"{len(index_lines)} lines; Claude Code loads the first {INDEX_LOAD_LINES}, "
                "so entries past that are never seen")
    else:
        add("dead-index", "MEMORY.md", "no MEMORY.md, so nothing in this folder is indexed")

    memories = {}
    by_name = {}
    for f in files:
        if f not in indexed:
            add("orphan", f, "not listed in MEMORY.md but still on disk and recallable")
        with open(os.path.join(memdir, f), encoding="utf-8") as fh:
            fields, body = parse_frontmatter(fh.read())
        if fields is None:
            add("frontmatter", f, "no frontmatter block (--- ... ---) at the top")
            memories[f] = ({}, body)
            continue
        memories[f] = (fields, body)
        name = fields.get("name", "")
        mtype = fields.get("metadata.type") or fields.get("type", "")
        missing = [k for k, v in (("name", name), ("description", fields.get("description", "")),
                                  ("type", mtype)) if not v]
        if missing:
            add("frontmatter", f, "missing " + ", ".join(missing))
        if mtype and mtype not in TYPES:
            add("bad-type", f, f"type '{mtype}'; expected one of {', '.join(sorted(TYPES))}")
        if name:
            if not SLUG.match(name):
                add("name-format", f, f"name '{name}' isn't lowercase-kebab-case")
            by_name.setdefault(name, []).append(f)

    for name, owners in by_name.items():
        if len(owners) > 1:
            for f in owners:
                others = ", ".join(o for o in owners if o != f)
                add("duplicate-name", f, f"name '{name}' is also used by {others}")

    home = os.path.expanduser("~")
    for f, (fields, body) in memories.items():
        stems = {os.path.splitext(g)[0]: (fl or {}).get("name") for g, (fl, _) in memories.items()}
        for link in sorted(set(WIKI_LINK.findall(CODE.sub("", body)))):
            link = link.strip()
            if link in by_name:
                continue
            guess = link.replace("_", "-") if link.replace("_", "-") in by_name else stems.get(link)
            hint = f"; did you mean [[{guess}]]?" if guess else ""
            add("dangling-link", f, f"[[{link}]] matches no memory's name{hint}")
        mtype = fields.get("metadata.type") or fields.get("type", "")
        seen = set()
        for raw in BACKTICK_PATH.findall(body):
            path = raw.rstrip(".,:;)")
            if path in seen or PLACEHOLDER.search(path) or path in ("/", "~"):
                continue
            seen.add(path)
            real = home + path[1:] if path.startswith("~") else path
            # A /path counts only if its top folder exists here. Otherwise it's a
            # slash command (/compact) or a URL path (/api/status), not a file.
            top = real.split("/")[1] if real.startswith("/") else ""
            if not path.startswith("~") and (path.count("/") < 2 or not os.path.isdir("/" + top)):
                continue
            if not os.path.exists(real):
                add("missing-path", f, f"names {path}, which doesn't exist")
            elif mtype == "project" and os.path.isfile(real):
                add("may-duplicate", f, f"names {path}; read both and check the memory isn't a second copy of it")
    return findings


def main(argv):
    args = [a for a in argv if a != "--json"]
    if len(args) != 1:
        print("usage: memory_audit.py MEMORY_DIR [--json]", file=sys.stderr)
        return 2
    memdir = os.path.expanduser(args[0])
    if not os.path.isdir(memdir):
        print(f"memory_audit: {memdir} is not a directory", file=sys.stderr)
        return 2

    findings = audit(memdir)
    errors = sum(1 for x in findings if x["severity"] == "error")
    if "--json" in argv:
        print(json.dumps({"dir": memdir, "findings": findings}, indent=2))
        return 1 if errors else 0

    count = sum(1 for f in os.listdir(memdir) if f.endswith(".md") and f != "MEMORY.md")
    print(f"Audited {count} memories in {memdir}")
    if not findings:
        print("No findings.")
    for sev in ("error", "warning", "note"):
        group = [x for x in findings if x["severity"] == sev]
        if not group:
            continue
        print(f"\n{sev.upper()}S ({len(group)})")
        for x in sorted(group, key=lambda x: (x["code"], x["file"])):
            print(f"  {x['code']:<15} {x['file']}: {x['detail']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
