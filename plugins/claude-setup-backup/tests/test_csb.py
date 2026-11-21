"""Tests for csb.py.

Every test runs against throwaway "machines" (temp home folders) that share a
local bare git repo as the backup remote. A fake `gh` answers the visibility
question, so nothing touches GitHub.

Each guard is tested from both sides: the clean case must pass, and the planted
defect must be caught. A check that only ever passes proves nothing.

Run:  python3 -m unittest discover plugins/claude-setup-backup/tests
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path, PurePosixPath, PureWindowsPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import csb  # noqa: E402

FAKE_GH = """#!/bin/sh
case "$2" in
  view) if [ "$FAKE_VIS" = MISSING ]; then echo "Could not resolve to a Repository" >&2; exit 1; fi
        echo "$FAKE_VIS" ;;
  create) exit 0 ;;
esac
"""


def quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(*a, **k)
    return rc, out.getvalue() + err.getvalue()


def tree(root: Path, with_git=True) -> dict:
    """Every file under root with its bytes: the 'nothing changed'
    fingerprint. with_git=False leaves out .git, for checks where a pull
    has legitimately run first."""
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file() and (with_git or ".git" not in p.relative_to(root).parts)}


def commits(bare: Path) -> int:
    r = subprocess.run(["git", "-C", str(bare), "rev-list", "--count", "main"],
                       capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 else 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="csb-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bare = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        gh = self.tmp / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.env = {"CSB_GH": str(gh), "FAKE_VIS": "PRIVATE", "CSB_GIT_URL": str(self.bare)}
        self.saved = {k: os.environ.get(k) for k in [*self.env, "CSB_HOME", "CLAUDE_CONFIG_DIR"]}
        os.environ.update(self.env)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.addCleanup(self.restore_env)

    def restore_env(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def machine(self, user: str) -> Path:
        """A home folder with a typical setup: CLAUDE.md importing a file,
        one command, one project memory, settings with a hook and an env key."""
        h = self.tmp / user
        ch = h / ".claude"
        (h / "cfg").mkdir(parents=True)
        (h / "cfg" / "rules.md").write_text("# Rules\nBe brief.\n")
        ch.mkdir()
        (ch / "CLAUDE.md").write_text("# Me\n\n@~/cfg/rules.md\n")
        (ch / "commands").mkdir()
        (ch / "commands" / "standup.md").write_text("Write my standup.\n")
        mem = ch / "projects" / (csb.encode(h) + "-proj") / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [Oncall](oncall.md) — handoff rules\n")
        (mem / "oncall.md").write_text("Handoff at 9am.\n")
        (ch / "settings.json").write_text(json.dumps({
            "env": {"MY_TOKEN": "not-a-real-value"},
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "notify-send hi"}]}]},
        }))
        return h

    def use(self, h: Path) -> Path:
        os.environ["CSB_HOME"] = str(h)
        return h

    def setup_backup(self, h: Path, remote=None):
        self.use(h)
        sel = csb.scan(h)
        return quiet(csb.init, h, remote or str(self.bare), sel, h / "backup")

    def mem_dir(self, h: Path, key="proj") -> Path:
        return h / ".claude" / "projects" / csb.memory_folder_name(key, h) / "memory"


class PathTranslation(unittest.TestCase):
    """Memory folders are named after the project's full path, so the same
    project has a different folder name on every machine."""

    def test_windows_and_linux_map_to_one_key(self):
        win, lin = PureWindowsPath(r"D:\people\alex"), PurePosixPath("/srv/alex")
        self.assertEqual(csb.encode(win / "proj"), "D--people-alex-proj")
        self.assertEqual(csb.memory_key("D--people-alex-proj", win), "proj")
        self.assertEqual(csb.memory_key("-srv-alex-proj", lin), "proj")
        self.assertEqual(csb.memory_folder_name("proj", win), "D--people-alex-proj")
        self.assertEqual(csb.memory_folder_name("proj", lin), "-srv-alex-proj")

    def test_home_prefix_needs_a_boundary(self):
        # /srv/alexander/proj is not inside /srv/alex
        key = csb.memory_key("-srv-alexander-proj", PurePosixPath("/srv/alex"))
        self.assertTrue(key.startswith(csb.ABS_PREFIX))
        self.assertEqual(csb.memory_folder_name(key, PurePosixPath("/elsewhere")), "-srv-alexander-proj")

    def test_special_keys_are_valid_folder_names(self):
        for key in (csb.HOME_KEY, csb.ABS_PREFIX + "x"):
            self.assertNotIn(":", key)
            self.assertNotIn(key, (".", ".."))

    def test_import_tokens_skip_mentions_emails_and_code(self):
        text = "@~/a.md\nping @alex\nmail alex@host\n`@pkg/name`\n```\n@~/fenced.md\n```\nsee @../b/c.md.\n"
        self.assertEqual(csb.import_tokens(text), ["~/a.md", "../b/c.md"])


class RoundTrip(Base):
    def test_clean_setup_passes_doctor(self):
        a = self.machine("alice")
        rc, out = self.setup_backup(a)
        self.assertEqual(rc, 0, out)
        rc, out = quiet(csb.doctor, a)
        self.assertEqual(rc, 0, out)
        self.assertEqual(commits(self.bare), 1)

    def test_restore_onto_a_machine_with_a_different_home(self):
        a = self.machine("alice")
        self.setup_backup(a)
        b = self.use(self.tmp / "bob")
        b.mkdir()
        rc, out = quiet(csb.restore, b, str(self.bare), b / "backup")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.mem_dir(b) / "oncall.md").read_text(), "Handoff at 9am.\n")
        self.assertTrue((b / ".claude" / "CLAUDE.md").is_file())
        self.assertEqual((b / "cfg" / "rules.md").read_text(), "# Rules\nBe brief.\n")
        self.assertTrue((b / ".claude" / "commands" / "standup.md").is_file())
        restored = json.loads((b / ".claude" / "settings.json").read_text())
        self.assertNotIn("env", restored)
        self.assertIn("SessionStart", restored["hooks"])
        self.assertIn("MY_TOKEN", out)  # told to set it by hand
        rc, out = quiet(csb.doctor, b)
        self.assertEqual(rc, 0, out)

    def test_edit_on_one_machine_reaches_the_other(self):
        a = self.machine("alice")
        self.setup_backup(a)
        b = self.use(self.tmp / "bob")
        b.mkdir()
        quiet(csb.restore, b, str(self.bare), b / "backup")
        (self.mem_dir(b) / "oncall.md").write_text("Handoff at 10am.\n")
        quiet(csb.sync, b)
        self.use(a)
        quiet(csb.sync, a)
        self.assertEqual((self.mem_dir(a) / "oncall.md").read_text(), "Handoff at 10am.\n")

    def test_both_sides_changed_keeps_both(self):
        a = self.machine("alice")
        self.setup_backup(a)
        b = self.use(self.tmp / "bob")
        b.mkdir()
        quiet(csb.restore, b, str(self.bare), b / "backup")
        (self.mem_dir(b) / "oncall.md").write_text("bob's version\n")
        quiet(csb.sync, b)
        self.use(a)
        (self.mem_dir(a) / "oncall.md").write_text("alice's version\n")
        rc, out = quiet(csb.sync, a)
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.mem_dir(a) / "oncall.md").read_text(), "alice's version\n")
        side = self.mem_dir(a) / ("oncall.md" + csb.CONFLICT_SUFFIX)
        self.assertEqual(side.read_text(), "bob's version\n")
        self.assertIn("conflict", out)


class Deletions(Base):
    """The bug this plugin exists to fix: a file deleted on one machine came
    back from the other one."""

    def _two_machines(self):
        a = self.machine("alice")
        self.setup_backup(a)
        b = self.use(self.tmp / "bob")
        b.mkdir()
        quiet(csb.restore, b, str(self.bare), b / "backup")
        self.use(a)
        (self.mem_dir(a) / "oncall.md").unlink()
        quiet(csb.sync, a)
        self.assertFalse((a / "backup" / "memory" / "proj" / "oncall.md").exists())
        return a, b

    def test_deletion_stays_deleted(self):
        a, b = self._two_machines()
        self.use(b)
        rc, out = quiet(csb.sync, b)
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.mem_dir(b) / "oncall.md").exists())
        self.assertFalse((b / "backup" / "memory" / "proj" / "oncall.md").exists())
        trashed = list((b / ".claude" / "claude-setup-backup-trash").rglob("oncall.md"))
        self.assertEqual(len(trashed), 1)  # moved aside, not destroyed
        self.use(a)
        quiet(csb.sync, a)
        self.assertFalse((self.mem_dir(a) / "oncall.md").exists())

    def test_without_the_last_sync_record_it_would_come_back(self):
        # Proves the test above can fail: wipe bob's record of what he last
        # synced, which is how a plain two-way copy behaves, and the deleted
        # file is pushed straight back into the backup.
        a, b = self._two_machines()
        self.use(b)
        st = json.loads(csb.state_path(b).read_text())
        st["base"] = {}
        csb.write_json(csb.state_path(b), st)
        quiet(csb.sync, b)
        self.assertTrue((b / "backup" / "memory" / "proj" / "oncall.md").exists())


class Privacy(Base):
    def test_public_repo_refused_at_setup(self):
        a = self.use(self.machine("alice"))
        os.environ["FAKE_VIS"] = "PUBLIC"
        with self.assertRaises(csb.CsbError) as cm:
            quiet(csb.init, a, "alex/setup", csb.scan(a), a / "backup")
        self.assertIn("public", str(cm.exception))
        self.assertFalse(csb.state_path(a).exists())
        self.assertEqual(commits(self.bare), 0)

    def test_private_repo_accepted_at_setup(self):
        a = self.use(self.machine("alice"))
        rc, out = quiet(csb.init, a, "alex/setup", csb.scan(a), a / "backup")
        self.assertEqual(rc, 0, out)
        self.assertEqual(commits(self.bare), 1)

    def test_repo_made_public_later_blocks_the_push(self):
        a = self.use(self.machine("alice"))
        quiet(csb.init, a, "alex/setup", csb.scan(a), a / "backup")
        (self.mem_dir(a) / "new.md").write_text("new memory\n")
        os.environ["FAKE_VIS"] = "PUBLIC"
        with self.assertRaises(csb.CsbError):
            quiet(csb.sync, a)
        self.assertEqual(commits(self.bare), 1)

    def test_unverifiable_remote_needs_explicit_opt_in(self):
        a = self.use(self.machine("alice"))
        with self.assertRaises(csb.CsbError) as cm:
            csb.require_private("ssh://git.example.org/alex/setup.git", False)
        self.assertIn("--allow-unverified", str(cm.exception))
        self.assertEqual(csb.require_private("ssh://git.example.org/alex/setup.git", True), "UNKNOWN")

    def test_env_values_never_reach_the_backup(self):
        a = self.machine("alice")
        self.setup_backup(a)
        backed = json.loads((a / "backup" / "claude" / "settings.json").read_text())
        self.assertEqual(backed["env"], {"MY_TOKEN": ""})
        live = json.loads((a / ".claude" / "settings.json").read_text())
        self.assertEqual(live["env"]["MY_TOKEN"], "not-a-real-value")  # live file untouched

    def test_key_in_a_memory_file_stops_the_sync(self):
        a = self.machine("alice")
        self.setup_backup(a)
        key = "sk" + "-ant-" + "x" * 40
        (self.mem_dir(a) / "leak.md").write_text(f"use {key}\n")
        before_repo, before_commits = tree(a / "backup", with_git=False), commits(self.bare)
        with self.assertRaises(csb.CsbError) as cm:
            quiet(csb.sync, a)
        self.assertIn("leak.md:1", str(cm.exception))
        self.assertNotIn(key, str(cm.exception))  # the error doesn't echo the key
        self.assertEqual(tree(a / "backup", with_git=False), before_repo)
        self.assertEqual(commits(self.bare), before_commits)

    def test_key_outside_env_in_settings_stops_the_sync(self):
        a = self.machine("alice")
        self.setup_backup(a)
        s = json.loads((a / ".claude" / "settings.json").read_text())
        s["apiKeyHelper"] = "echo " + "gh" + "p_" + "y" * 36
        (a / ".claude" / "settings.json").write_text(json.dumps(s))
        with self.assertRaises(csb.CsbError):
            quiet(csb.sync, a)

    def test_clean_memory_syncs(self):
        a = self.machine("alice")
        self.setup_backup(a)
        (self.mem_dir(a) / "fine.md").write_text("talk about token budgets and sk-learn\n")
        rc, out = quiet(csb.sync, a)
        self.assertEqual(rc, 0, out)


class Doctor(Base):
    def test_broken_import_goes_red(self):
        a = self.machine("alice")
        self.setup_backup(a)
        rc, _ = quiet(csb.doctor, a)
        self.assertEqual(rc, 0)
        # the one-letter typo that started all this
        (a / ".claude" / "CLAUDE.md").write_text("# Me\n\n@~/cgf/rules.md\n")
        rc, out = quiet(csb.doctor, a)
        self.assertGreaterEqual(rc, 1)
        self.assertIn("@~/cgf/rules.md", out)

    def test_dead_memory_index_link_goes_red(self):
        a = self.machine("alice")
        self.setup_backup(a)
        (self.mem_dir(a) / "MEMORY.md").write_text("- [Gone](gone.md) — deleted\n")
        rc, out = quiet(csb.doctor, a)
        self.assertGreaterEqual(rc, 1)
        self.assertIn("gone.md", out)

    def test_missing_hook_goes_red(self):
        a = self.machine("alice")
        self.setup_backup(a)
        (a / ".claude" / "settings.json").write_text("{}")
        rc, out = quiet(csb.doctor, a)
        self.assertGreaterEqual(rc, 1)
        self.assertIn("notify-send hi", out)

    def test_not_set_up_goes_red(self):
        a = self.use(self.machine("alice"))
        rc, out = quiet(csb.doctor, a)
        self.assertGreaterEqual(rc, 1)
        self.assertIn("isn't set up", out)


class DryRun(Base):
    def test_dry_run_writes_nothing(self):
        a = self.machine("alice")
        self.setup_backup(a)
        (self.mem_dir(a) / "oncall.md").write_text("changed\n")
        (self.mem_dir(a) / "new.md").write_text("new\n")
        before_home, before_commits = tree(a), commits(self.bare)
        rc, out = quiet(csb.sync, a, dry_run=True)
        self.assertEqual(rc, 0, out)
        self.assertIn("would push", out)
        self.assertEqual(tree(a), before_home)
        self.assertEqual(commits(self.bare), before_commits)
        rc, out = quiet(csb.sync, a)  # and the real run does write
        self.assertEqual(commits(self.bare), before_commits + 1)

    def test_restore_dry_run_writes_nothing(self):
        a = self.machine("alice")
        self.setup_backup(a)
        b = self.use(self.tmp / "bob")
        b.mkdir()
        rc, out = quiet(csb.restore, b, str(self.bare), b / "backup", dry_run=True)
        self.assertEqual(rc, 0, out)
        self.assertIn("would restore", out)
        self.assertIn("memory/proj/oncall.md", out)
        self.assertEqual(tree(b), {})  # not even the backup clone or the state file


if __name__ == "__main__":
    unittest.main()
