"""Tests for memory_audit.py.

Each test starts from a clean memory folder that must produce no findings at all,
plants one defect, and asserts that exactly that defect is reported. The clean
case matters as much as the defects: a checker that flags everything also
"catches" every planted defect.

Run:  python3 -m unittest discover plugins/memory-audit/tests
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "memory-audit", "scripts"))
import memory_audit  # noqa: E402

INDEX = """# Memory Index

- [On-call handoff](oncall_handoff.md) — what the handoff note must include
- [Team](team.md) — who owns what
"""

ONCALL = """---
name: oncall-handoff
description: "Handoff notes list open incidents, owners and the next check time"
metadata:
  type: feedback
---

Every handoff names the next check time, not "later".
**Why:** two incidents sat unowned overnight. See [[team]].
**How to apply:** ask for the time before writing the note. Script: `{script}`.
Bash test syntax in a code span is not a link: `[[ -f x ]]`.
Neither is a slash command: `/compact`.
"""

TEAM = """---
name: team
description: Who owns which service
type: user
---

Payments is owned by the platform team. See [[oncall-handoff]].
"""


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.script = os.path.join(self.dir, "handoff-check.sh")
        self.write("handoff-check.sh", "#!/bin/sh\n")
        self.write("MEMORY.md", INDEX)
        self.write("oncall_handoff.md", ONCALL.format(script=self.script))
        self.write("team.md", TEAM)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def edit(self, name, old, new):
        path = os.path.join(self.dir, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text, f"fixture edit missed in {name}")
        self.write(name, text.replace(old, new, 1))

    def codes(self):
        return sorted(f["code"] for f in memory_audit.audit(self.dir))

    def test_clean_folder_has_no_findings(self):
        self.assertEqual(self.codes(), [])

    def test_orphan(self):
        self.edit("MEMORY.md", "- [Team](team.md) — who owns what\n", "")
        self.assertEqual(self.codes(), ["orphan"])

    def test_dead_index(self):
        self.edit("MEMORY.md", "who owns what\n", "who owns what\n- [Gone](gone.md) — retired\n")
        self.assertEqual(self.codes(), ["dead-index"])

    def test_no_index_at_all(self):
        os.remove(os.path.join(self.dir, "MEMORY.md"))
        self.assertEqual(self.codes(), ["dead-index", "orphan", "orphan"])

    def test_no_frontmatter(self):
        self.write("team.md", "Payments is owned by the platform team. See [[oncall-handoff]].\n")
        # Without frontmatter it has no name, so the link to it dangles too.
        self.assertEqual(self.codes(), ["dangling-link", "frontmatter"])

    def test_no_frontmatter_but_a_divider_later(self):
        # A --- divider further down must not be read as the end of frontmatter.
        self.write("team.md", "Payments: platform team.\n\n---\n\nname: team\ntype: user\n---\n")
        details = [f["detail"] for f in memory_audit.audit(self.dir) if f["code"] == "frontmatter"]
        self.assertEqual(details, ["no frontmatter block (--- ... ---) at the top"])

    def test_missing_description(self):
        self.edit("team.md", "description: Who owns which service\n", "")
        self.assertEqual(self.codes(), ["frontmatter"])

    def test_missing_type(self):
        self.edit("team.md", "type: user\n", "")
        self.assertEqual(self.codes(), ["frontmatter"])

    def test_bad_type(self):
        self.edit("oncall_handoff.md", "  type: feedback", "  type: preference")
        self.assertEqual(self.codes(), ["bad-type"])

    def test_duplicate_name(self):
        self.edit("team.md", "name: team", "name: oncall-handoff")
        # Both files report it, and [[team]] no longer resolves.
        self.assertEqual(self.codes(), ["dangling-link", "duplicate-name", "duplicate-name"])

    def test_name_format(self):
        self.edit("team.md", "name: team", "name: Team_Owners")
        self.assertIn("name-format", self.codes())

    def test_dangling_link_with_hint(self):
        self.edit("team.md", "[[oncall-handoff]]", "[[oncall_handoff]]")
        findings = memory_audit.audit(self.dir)
        self.assertEqual([f["code"] for f in findings], ["dangling-link"])
        self.assertIn("did you mean [[oncall-handoff]]", findings[0]["detail"])

    def test_missing_path(self):
        os.remove(self.script)
        self.assertEqual(self.codes(), ["missing-path"])

    def test_missing_home_path(self):
        self.edit("team.md", "platform team.", "platform team. Runbook: `~/no-such-folder-memory-audit/runbook.md`.")
        self.assertEqual(self.codes(), ["missing-path"])

    def test_may_duplicate_only_for_project_memories(self):
        self.edit("oncall_handoff.md", "  type: feedback", "  type: project")
        self.assertEqual(self.codes(), ["may-duplicate"])

    def test_index_length(self):
        self.edit("MEMORY.md", "# Memory Index\n", "# Memory Index\n" + "\n" * 200)
        self.assertEqual(self.codes(), ["index-length"])

    def test_cli_exit_codes(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(memory_audit.main([self.dir]), 0)
            # Warnings and notes alone don't fail the run; errors do.
            self.edit("oncall_handoff.md", "  type: feedback", "  type: project")
            self.assertEqual(memory_audit.main([self.dir]), 0)
            self.edit("MEMORY.md", "- [Team](team.md) — who owns what\n", "")
            self.assertEqual(memory_audit.main([self.dir]), 1)
            self.assertEqual(memory_audit.main([os.path.join(self.dir, "nope")]), 2)

    def test_never_writes(self):
        before = {f: os.path.getmtime(os.path.join(self.dir, f)) for f in os.listdir(self.dir)}
        self.edit("MEMORY.md", "- [Team](team.md) — who owns what\n", "")
        before["MEMORY.md"] = os.path.getmtime(os.path.join(self.dir, "MEMORY.md"))
        with redirect_stdout(io.StringIO()):
            memory_audit.main([self.dir])
            memory_audit.main([self.dir, "--json"])
        after = {f: os.path.getmtime(os.path.join(self.dir, f)) for f in os.listdir(self.dir)}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
