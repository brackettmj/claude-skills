#!/usr/bin/env python3
"""claude-setup-backup: back up a Claude Code setup to a private git repo, and
rebuild a machine from it.

What it backs up: ~/.claude/CLAUDE.md and every file it @-imports, the memory
folder of every project, custom commands/agents/skills/output styles, the hooks
and status line from settings.json (secret values blanked), and any extra
files you name. What it never backs up: env values, API keys, ~/.claude.json,
session transcripts.

    csb.py scan [--json]                     what's on this machine
    csb.py init --remote OWNER/NAME --select FILE [--create] [--auto-sync]
    csb.py sync [--dry-run] [--quiet] [-m MSG]
    csb.py restore --remote OWNER/NAME [--dry-run]
    csb.py doctor [--quiet]                  exit code = number of FAILs
    csb.py hook start|end                    for the plugin's session hooks

Standard library only. Runs on Linux, macOS and Windows.
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

VERSION = "0.1.0"
MANIFEST = "manifest.json"
STATE_FILE = "claude-setup-backup.local.json"
CHECKLIST = "REBUILD.md"
DIRS = ["commands", "agents", "skills", "output-styles"]
SKIP_NAMES = {".git", "__pycache__", ".DS_Store"}
CONFLICT_SUFFIX = ".from-backup"
HOME_KEY = "_home_"
ABS_PREFIX = "_abs_"
STALE_DAYS = 7

# Key shapes that must never reach the backup. Prefixes are split so this file
# doesn't trip secret scanners that read it.
SECRET_PATTERNS = [re.compile(p) for p in (
    "sk" + r"-ant-[A-Za-z0-9_-]{20,}",
    "sk" + r"-or-v1-[A-Za-z0-9]{20,}",
    "sk" + r"-(?:proj-)?[A-Za-z0-9_-]{32,}",
    "AK" + r"IA[0-9A-Z]{16}",
    "gh" + r"[pousr]_[A-Za-z0-9]{30,}",
    "github" + r"_pat_[A-Za-z0-9_]{40,}",
    "xo" + r"x[abpr]-[A-Za-z0-9-]{10,}",
    "AI" + r"za[0-9A-Za-z_-]{35}",
    "-----BEGIN " + r"[A-Z ]*PRIVATE KEY-----",
)]


class CsbError(Exception):
    """A problem the user has to fix. Printed without a traceback."""


# --------------------------------------------------------------------------
# where things live

def home() -> Path:
    return Path(os.environ.get("CSB_HOME") or Path.home())


def claude_home(h: Path) -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else h / ".claude"


def default_repo_dir(h: Path) -> Path:
    return h / "claude-setup-backup"


def encode(p) -> str:
    """Claude Code names a project's folder by replacing every character that
    isn't a letter or digit with '-': /srv/alex/proj -> -srv-alex-proj."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(p))


def memory_key(folder_name: str, h) -> str:
    """Machine-independent name for a project's memory folder. The home prefix
    is stripped, so -srv-alex-proj (Linux) and D--people-alex-proj (Windows)
    are both 'proj'. Encoded names never contain '_', so the two special keys
    can't collide with a real one: _home_ is home itself, and _abs_<name> is a
    project outside home, which only restores onto a machine with the same
    layout."""
    hp = encode(h)
    if folder_name == hp:
        return HOME_KEY
    if folder_name.startswith(hp + "-"):
        return folder_name[len(hp) + 1:]
    return ABS_PREFIX + folder_name


def memory_folder_name(key: str, h) -> str:
    if key == HOME_KEY:
        return encode(h)
    if key.startswith(ABS_PREFIX):
        return key[len(ABS_PREFIX):]
    return encode(h) + "-" + key


def locate_project(key: str, h: Path):
    """Best guess at the real directory behind a memory key, by walking home and
    matching encoded names. Only used for display and repo detection."""
    if key == HOME_KEY:
        return h
    if key.startswith(ABS_PREFIX):
        return None

    def walk(cur: Path, rest: str, depth: int):
        if depth > 10:
            return None
        try:
            children = sorted(c for c in cur.iterdir() if c.is_dir() and not c.is_symlink())
        except OSError:
            return None
        for c in children:
            e = encode(c.name)
            if rest == e:
                return c
            if rest.startswith(e + "-"):
                hit = walk(c, rest[len(e) + 1:], depth + 1)
                if hit:
                    return hit
        return None

    return walk(h, key, 0)


def files_under(root: Path):
    """Relative posix paths of every regular file under root, skipping noise."""
    out = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for f in filenames:
            if f in SKIP_NAMES or f.endswith(CONFLICT_SUFFIX):
                continue
            p = Path(dirpath) / f
            if p.is_file():
                out.append(p.relative_to(root).as_posix())
    return sorted(out)


def sha(p: Path):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except (FileNotFoundError, IsADirectoryError):
        return None


def under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# CLAUDE.md imports

IMPORT_RE = re.compile(r"(?:^|(?<=\s))@(\S+)")


def import_tokens(text: str):
    """@-import tokens outside code fences and inline code. A token counts as a
    path when it has a slash or a file extension, so '@alex' mentions and
    emails (no leading space) are ignored."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        for tok in IMPORT_RE.findall(line):
            tok = tok.rstrip(".,;:)")
            if "/" in tok or "\\" in tok or re.search(r"\.[A-Za-z0-9]{1,5}$", tok):
                out.append(tok)
    return out


def resolve_import(tok: str, from_file: Path, h: Path) -> Path:
    if tok.startswith("~/") or tok.startswith("~\\"):
        return h / tok[2:]
    p = Path(tok)
    return p if p.is_absolute() else (from_file.parent / p)


def walk_imports(root_file: Path, h: Path):
    """Returns (found, missing): resolved files reachable from root_file, and
    (token, file, resolved) for imports that don't resolve."""
    found, missing, seen = [], [], set()
    queue = [(root_file, 0)]
    while queue:
        f, depth = queue.pop(0)
        if depth > 5 or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for tok in import_tokens(text):
            target = resolve_import(tok, f, h)
            key = os.path.normcase(os.path.abspath(target))
            if key in seen:
                continue
            seen.add(key)
            if target.is_file():
                found.append(Path(os.path.abspath(target)))
                queue.append((target, depth + 1))
            else:
                missing.append((tok, f, target))
    return found, missing


# --------------------------------------------------------------------------
# settings.json

def scrub_settings(data: dict) -> dict:
    """Copy of settings with every env value blanked. Keys stay, so the rebuild
    checklist can say which variables to set."""
    out = json.loads(json.dumps(data))
    if isinstance(out.get("env"), dict):
        out["env"] = {k: "" for k in out["env"]}
    return out


def hook_commands(settings: dict):
    """(event, command) for every command hook, plus the status line."""
    out = []
    for event, groups in (settings.get("hooks") or {}).items():
        for g in groups or []:
            for hk in (g or {}).get("hooks", []) or []:
                if hk.get("type") == "command" and hk.get("command"):
                    out.append((event, hk["command"]))
    sl = settings.get("statusLine") or {}
    if isinstance(sl, dict) and sl.get("command"):
        out.append(("statusLine", sl["command"]))
    return out


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise CsbError(f"{p} is not valid JSON: {e}")


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# scan

def scan(h: Path) -> dict:
    ch = claude_home(h)
    res = {"home": str(h), "claude_home": str(ch)}
    cm = ch / "CLAUDE.md"
    res["claude_md"] = {"exists": cm.is_file(), "include": cm.is_file()}
    imports, outside = [], []
    if cm.is_file():
        found, missing = walk_imports(cm, h)
        for f in found:
            if under(f, h) and not under(f, ch):
                imports.append(Path(os.path.relpath(f, h)).as_posix())
            elif not under(f, ch):
                outside.append(str(f))
        res["imports_missing"] = [m[0] for m in missing]
    res["imports"] = imports
    res["imports_outside_home"] = outside
    res["dirs"] = [{"name": d, "files": len(files_under(ch / d)),
                    "bytes": sum((ch / d / f).stat().st_size for f in files_under(ch / d)),
                    "include": True}
                   for d in DIRS if files_under(ch / d)]
    mem, repos = [], []
    proj = ch / "projects"
    if proj.is_dir():
        for folder in sorted(proj.iterdir()):
            md = folder / "memory"
            n = len(files_under(md))
            if not n:
                continue
            key = memory_key(folder.name, h)
            loc = locate_project(key, h)
            mem.append({"key": key, "files": n,
                        "path": (Path(os.path.relpath(loc, h)).as_posix() if loc else None),
                        "include": not key.startswith(ABS_PREFIX)})
            if loc and (loc / ".git").exists():
                url = git_out(loc, "config", "--get", "remote.origin.url")
                if url:
                    repos.append({"path": Path(os.path.relpath(loc, h)).as_posix(),
                                  "url": url, "include": True})
    res["memory"] = mem
    res["repos"] = repos
    s = read_json(ch / "settings.json", {}) or {}
    res["settings"] = {"exists": (ch / "settings.json").is_file(),
                       "hooks": len(hook_commands(s)),
                       "env_keys": sorted((s.get("env") or {}).keys()),
                       "include": (ch / "settings.json").is_file()}
    res["extra"] = []
    return res


def print_scan(r: dict) -> None:
    print(f"Claude home: {r['claude_home']}")
    print(f"  CLAUDE.md: {'yes' if r['claude_md']['exists'] else 'none'}")
    for i in r["imports"]:
        print(f"  import: ~/{i}")
    for i in r["imports_outside_home"]:
        print(f"  import outside home (not backed up): {i}")
    for m in r.get("imports_missing", []):
        print(f"  BROKEN import: @{m}")
    for d in r["dirs"]:
        print(f"  {d['name']}/: {d['files']} files, {d['bytes'] / 1e6:.1f} MB")
    for m in r["memory"]:
        where = ("~" if m["path"] == "." else f"~/{m['path']}") if m["path"] else "(folder not found)"
        print(f"  memory {m['key']}: {m['files']} files  {where}")
    for rp in r["repos"]:
        print(f"  repo ~/{rp['path']}: {rp['url']}")
    s = r["settings"]
    print(f"  settings.json: {s['hooks']} hooks, env keys: {', '.join(s['env_keys']) or 'none'}")


# --------------------------------------------------------------------------
# git and the remote

def git(repo: Path, *args, check=True, quiet=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    ident = []
    if not git_out(repo, "config", "user.email"):
        ident = ["-c", "user.name=claude-setup-backup", "-c", "user.email=csb@localhost"]
    r = subprocess.run(["git", *ident, "-C", str(repo), *args], capture_output=True,
                       text=True, env=env)
    if check and r.returncode != 0:
        raise CsbError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r


def git_out(repo: Path, *args) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def is_github_spec(spec: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec)) and not Path(spec).exists()


def visibility(spec: str) -> str:
    """PRIVATE, PUBLIC, INTERNAL, MISSING, LOCAL (a path on this machine) or
    UNKNOWN (a remote we can't ask)."""
    if not is_github_spec(spec):
        m = re.match(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$", spec)
        if m:
            spec = m.group(1)
        elif Path(spec).exists() or spec.startswith("file://"):
            return "LOCAL"
        else:
            return "UNKNOWN"
    gh = os.environ.get("CSB_GH", "gh")
    try:
        r = subprocess.run([gh, "repo", "view", spec, "--json", "visibility", "-q", ".visibility"],
                           capture_output=True, text=True)
    except OSError:
        raise CsbError("the GitHub CLI (gh) isn't installed, so the repo's visibility can't be "
                       "checked. Install gh and run `gh auth login`.")
    if r.returncode != 0:
        if "Could not resolve" in r.stderr or "not found" in r.stderr.lower():
            return "MISSING"
        raise CsbError(f"gh couldn't check {spec}: {r.stderr.strip()}")
    return r.stdout.strip().upper() or "UNKNOWN"


def require_private(spec: str, allow_unverified: bool) -> str:
    v = visibility(spec)
    if v in ("PRIVATE", "LOCAL"):
        return v
    if v == "UNKNOWN" and allow_unverified:
        return v
    if v == "UNKNOWN":
        raise CsbError(f"can't verify that {spec} is private. Memory holds personal detail, so "
                       "this refuses unverified remotes. If you're sure it's private, pass "
                       "--allow-unverified.")
    if v == "MISSING":
        raise CsbError(f"{spec} doesn't exist. Pass --create to make it as a private repo.")
    raise CsbError(f"{spec} is {v.lower()}, not private. Refusing: your memory and CLAUDE.md "
                   "would be readable by others. Make the repo private first.")


def git_url(spec: str) -> str:
    return f"https://github.com/{spec}.git" if is_github_spec(spec) else spec


# --------------------------------------------------------------------------
# state

def state_path(h: Path) -> Path:
    return claude_home(h) / STATE_FILE


def load_state(h: Path) -> dict:
    s = read_json(state_path(h))
    if not s:
        raise CsbError("this machine isn't set up yet. Run /claude-setup-backup:setup "
                       "(new backup) or /claude-setup-backup:restore (existing backup).")
    return s


def load_manifest(repo: Path) -> dict:
    m = read_json(repo / MANIFEST)
    if not m:
        raise CsbError(f"{repo} has no {MANIFEST}; it isn't a claude-setup-backup repo.")
    return m


# --------------------------------------------------------------------------
# the file map: repo path -> live path

def file_map(man: dict, repo: Path, h: Path) -> dict:
    ch = claude_home(h)
    pairs = {}
    if man.get("claude_md"):
        pairs["claude/CLAUDE.md"] = ch / "CLAUDE.md"
        if (ch / "CLAUDE.md").is_file():
            for f in walk_imports(ch / "CLAUDE.md", h)[0]:
                if under(f, h) and not under(f, ch):
                    pairs["home/" + Path(os.path.relpath(f, h)).as_posix()] = f
    for d in man.get("dirs", []):
        for rel in set(files_under(ch / d)) | set(files_under(repo / "claude" / d)):
            pairs[f"claude/{d}/{rel}"] = ch / d / rel
    excl = set(man.get("memory_exclude", []))
    if man.get("memory", True):
        keys = set()
        if (ch / "projects").is_dir():
            for folder in (ch / "projects").iterdir():
                if (folder / "memory").is_dir():
                    keys.add(memory_key(folder.name, h))
        if (repo / "memory").is_dir():
            keys |= {p.name for p in (repo / "memory").iterdir() if p.is_dir()}
        for key in sorted(keys - excl):
            live = ch / "projects" / memory_folder_name(key, h) / "memory"
            for rel in set(files_under(live)) | set(files_under(repo / "memory" / key)):
                pairs[f"memory/{key}/{rel}"] = live / rel
    for rel in man.get("extra", []):
        live = h / rel
        if live.is_dir() or (repo / "home" / rel).is_dir():
            for sub in set(files_under(live)) | set(files_under(repo / "home" / rel)):
                pairs[f"home/{rel}/{sub}"] = live / sub
        else:
            pairs[f"home/{rel}"] = live
    # imports that only exist in the backup still restore (new machine)
    if man.get("claude_md") and (repo / "home").is_dir():
        for rel in files_under(repo / "home"):
            pairs.setdefault("home/" + rel, h / rel)
    return pairs


# --------------------------------------------------------------------------
# sync: a three-way merge against what this machine saw at its last sync

def plan(pairs: dict, repo: Path, base: dict):
    acts = []
    for rel in sorted(pairs):
        rh, lh, bh = sha(repo / rel), sha(pairs[rel]), base.get(rel)
        if rh == lh:
            continue
        if lh is None:
            acts.append(("drop-backup" if bh is not None and bh == rh else "pull", rel))
        elif rh is None:
            acts.append(("drop-live" if bh is not None and bh == lh else "push", rel))
        elif bh == lh:
            acts.append(("pull", rel))
        elif bh == rh:
            acts.append(("push", rel))
        else:
            acts.append(("conflict", rel))
    return acts


def secret_hits(items):
    """items: (label, Path or str). Returns 'label:line' for each line that
    looks like it holds a key."""
    hits = []
    for label, src in items:
        if isinstance(src, str):
            text = src
        else:
            try:
                text = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        for n, line in enumerate(text.splitlines(), 1):
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    hits.append(f"{label}:{n}")
                    break
    return hits


def trash_dir(h: Path) -> Path:
    return claude_home(h) / "claude-setup-backup-trash" / datetime.date.today().isoformat()


def remote_has_main(repo: Path) -> bool:
    r = git(repo, "ls-remote", "--heads", "origin", "main", check=False)
    if r.returncode != 0:
        raise CsbError(f"can't reach the backup remote: {r.stderr.strip()}")
    return bool(r.stdout.strip())


def write_checklist(man: dict, repo: Path, spec: str) -> None:
    s = read_json(repo / "claude" / "settings.json", {}) or {}
    tools = sorted({cmd.split()[0].strip("\"'") for _, cmd in hook_commands(s)})
    env = sorted((s.get("env") or {}).keys())
    lines = [
        "# Rebuilding this Claude Code setup",
        "",
        "Written by claude-setup-backup on every sync. Don't edit it here; it gets rewritten.",
        "",
        "1. Install Claude Code and git. For a GitHub backup, also install the GitHub CLI",
        "   and run `gh auth login`.",
        "2. In Claude Code:",
        "",
        "       /plugin marketplace add brackettmj/claude-skills",
        "       /plugin install claude-setup-backup@brackettmj-skills",
        f"       /claude-setup-backup:restore {spec}",
        "",
    ]
    repos = man.get("repos", [])
    if repos:
        lines += ["3. Clone your repos (restore offers to do this for you):", ""]
        lines += [f"       git clone {r['url']} ~/{r['path']}" for r in repos]
        lines.append("")
    if env:
        lines += ["4. Set these values in `~/.claude/settings.json` → `env`. Only the names were",
                  "   backed up:", ""]
        lines += [f"   - `{k}`" for k in env]
        lines.append("")
    if tools:
        lines += ["5. Install what your hooks and status line call:", ""]
        lines += [f"   - `{t}`" for t in tools]
        lines.append("")
    lines += [
        "6. Run `/claude-setup-backup:doctor`. Every line should say `ok`.",
        "",
        "## Not in this backup",
        "",
        "- Secret values (env values are blanked; API keys are refused).",
        "- `~/.claude.json` (your account and MCP servers) and session transcripts.",
        "- Memory for projects outside your home folder only restores onto a machine",
        "  with the same folder layout.",
        "",
    ]
    (repo / CHECKLIST).write_text("\n".join(lines), encoding="utf-8")


def sync(h: Path, dry_run=False, quiet=False, message=None, pull_remote=True) -> int:
    st = load_state(h)
    repo = Path(st["repo_dir"])
    if not (repo / ".git").exists():
        raise CsbError(f"backup clone {repo} is missing. Run /claude-setup-backup:restore "
                       f"{st.get('remote', '')}")
    require_private(st["remote"], st.get("allow_unverified", False))
    say = (lambda *a: None) if quiet else print

    # A dry run doesn't fetch either: it touches nothing, .git included, so it
    # compares against the backup as of this machine's last sync.
    if pull_remote and not dry_run and remote_has_main(repo):
        git(repo, "pull", "-q", "--rebase", "--autostash", "origin", "main")
    man = load_manifest(repo)
    pairs = file_map(man, repo, h)
    acts = plan(pairs, repo, st.get("base", {}))

    ch = claude_home(h)
    settings_live = read_json(ch / "settings.json") if man.get("settings") else None
    scrubbed = scrub_settings(settings_live) if settings_live is not None else None

    outgoing = [(str(pairs[rel]), pairs[rel]) for k, rel in acts if k in ("push", "conflict")]
    if scrubbed is not None:
        outgoing.append((str(ch / "settings.json") + " (outside env)", json.dumps(scrubbed, indent=1)))
    hits = secret_hits(outgoing)
    if hits:
        raise CsbError("found what looks like an API key or private key, so nothing was synced. "
                       "Remove it, then sync again:\n  " + "\n  ".join(hits))

    if dry_run:
        for k, rel in acts:
            print(f"would {k:12} {rel}")
        if not acts:
            print("nothing to do: this machine and the backup match")
        return 0

    conflicts = []
    for k, rel in acts:
        live, bk = pairs[rel], repo / rel
        if k == "pull":
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bk, live)
        elif k == "push":
            bk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, bk)
        elif k == "drop-backup":
            bk.unlink()
        elif k == "drop-live":
            t = trash_dir(h) / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(live), str(t))
        elif k == "conflict":
            shutil.copy2(bk, Path(str(live) + CONFLICT_SUFFIX))
            shutil.copy2(live, bk)
            conflicts.append(live)
    if scrubbed is not None:
        write_json(repo / "claude" / "settings.json", scrubbed)
    write_checklist(man, repo, st["remote"])

    git(repo, "add", "-A")
    changed = bool(git_out(repo, "status", "--porcelain"))
    if changed:
        counts = {}
        for k, _ in acts:
            counts[k] = counts.get(k, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "settings/checklist"
        git(repo, "commit", "-q", "-m", message or f"sync from {platform.node() or 'a machine'}: {summary}")
    ahead = git_out(repo, "rev-list", "--count", "@{u}..HEAD") if git_out(repo, "rev-parse", "--abbrev-ref", "@{u}") else "1"
    if changed or ahead not in ("", "0"):
        require_private(st["remote"], st.get("allow_unverified", False))
        git(repo, "push", "-q", "-u", "origin", "HEAD:main")

    st["base"] = {rel: sha(repo / rel) for rel in pairs if (repo / rel).is_file()}
    st["last_sync"] = datetime.datetime.now().isoformat(timespec="seconds")
    write_json(state_path(h), st)

    n = {k: sum(1 for a, _ in acts if a == k) for k in ("pull", "push", "drop-backup", "drop-live", "conflict")}
    say(f"synced: {n['pull']} in from backup, {n['push']} out to backup, "
        f"{n['drop-backup'] + n['drop-live']} deletions carried over, {n['conflict']} conflicts")
    for c in conflicts:
        say(f"  conflict: kept your copy of {c}; the backup's version is beside it as "
            f"{c.name}{CONFLICT_SUFFIX}")
    if n["drop-live"]:
        say(f"  files deleted on another machine were moved to {trash_dir(h)}")
    return 0


# --------------------------------------------------------------------------
# init / restore

def init(h: Path, remote: str, select: dict, repo_dir: Path, create=False, auto_sync=False,
         allow_unverified=False) -> int:
    if state_path(h).exists():
        raise CsbError(f"already set up (see {state_path(h)}). Run sync instead.")
    v = visibility(remote)
    if v == "MISSING" and create:
        gh = os.environ.get("CSB_GH", "gh")
        r = subprocess.run([gh, "repo", "create", remote, "--private"], capture_output=True, text=True)
        if r.returncode != 0:
            raise CsbError(f"couldn't create {remote}: {r.stderr.strip()}")
    require_private(remote, allow_unverified)
    url = os.environ.get("CSB_GIT_URL") or git_url(remote)
    if not (repo_dir / ".git").exists():
        repo_dir.mkdir(parents=True, exist_ok=True)
        git(repo_dir, "init", "-q", "-b", "main")
        git(repo_dir, "remote", "add", "origin", url)
    if remote_has_main(repo_dir):
        git(repo_dir, "pull", "-q", "origin", "main")
    if (repo_dir / MANIFEST).exists():
        raise CsbError(f"{remote} already holds a backup. Use restore on this machine instead.")
    man = {
        "version": 1,
        "claude_md": bool(select.get("claude_md", {}).get("include")),
        "dirs": [d["name"] for d in select.get("dirs", []) if d.get("include")],
        "memory": True,
        "memory_exclude": [m["key"] for m in select.get("memory", []) if not m.get("include")],
        "settings": bool(select.get("settings", {}).get("include")),
        "repos": [{"path": r["path"], "url": r["url"]} for r in select.get("repos", []) if r.get("include")],
        "extra": [e if isinstance(e, str) else e["path"] for e in select.get("extra", [])
                  if isinstance(e, str) or e.get("include", True)],
        "auto_sync": bool(auto_sync),
    }
    write_json(repo_dir / MANIFEST, man)
    write_json(state_path(h), {"repo_dir": str(repo_dir), "remote": remote,
                               "allow_unverified": allow_unverified, "base": {}})
    return sync(h, message="first backup")


def restore(h: Path, remote: str, repo_dir: Path, dry_run=False, allow_unverified=False) -> int:
    require_private(remote, allow_unverified)
    url = os.environ.get("CSB_GIT_URL") or git_url(remote)

    def clone(dest: Path):
        r = subprocess.run(["git", "clone", "-q", url, str(dest)], capture_output=True,
                           text=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        if r.returncode != 0:
            raise CsbError(f"couldn't clone {remote}: {r.stderr.strip()}")

    if dry_run:
        # Clone into a temp folder and plan against an empty history, so the
        # preview writes nothing on this machine.
        with tempfile.TemporaryDirectory() as td:
            tmp_repo = Path(td) / "backup"
            clone(tmp_repo)
            man = load_manifest(tmp_repo)
            acts = plan(file_map(man, tmp_repo, h), tmp_repo, {})
            labels = {"pull": "restore", "push": "back up", "conflict": "keep yours, save backup's beside it"}
            for k, rel in acts:
                print(f"would {labels.get(k, k):12} {rel}")
            if not acts:
                print("nothing to do: this machine already matches the backup")
        return 0

    if not (repo_dir / ".git").exists():
        clone(repo_dir)
    load_manifest(repo_dir)
    if not state_path(h).exists():
        write_json(state_path(h), {"repo_dir": str(repo_dir), "remote": remote,
                                   "allow_unverified": allow_unverified, "base": {}})
    rc = sync(h, message="restore onto a new machine")
    ch = claude_home(h)
    bk = read_json(repo_dir / "claude" / "settings.json")
    if bk is not None and not (ch / "settings.json").exists():
        env = bk.pop("env", None) or {}
        write_json(ch / "settings.json", bk)
        print(f"wrote {ch / 'settings.json'} from the backup (hooks and status line)")
        if env:
            print("  set these env values yourself; only the names were backed up: " + ", ".join(sorted(env)))
    print(f"rebuild checklist: {repo_dir / CHECKLIST}")
    return rc


# --------------------------------------------------------------------------
# doctor

def doctor(h: Path, quiet=False) -> int:
    fails = 0
    ch = claude_home(h)

    def ok(m):
        if not quiet:
            print(f"ok    {m}")

    def fail(m):
        nonlocal fails
        fails += 1
        print(f"FAIL  {m}")

    def warn(m):
        print(f"warn  {m}")

    cm = ch / "CLAUDE.md"
    if cm.is_file():
        found, missing = walk_imports(cm, h)
        for tok, f, target in missing:
            fail(f"{f.name} imports @{tok}, but {target} doesn't exist. Claude Code skips "
                 "it silently, so everything in that file is missing from your sessions.")
        if not missing:
            ok(f"CLAUDE.md and its {len(found)} import(s) all resolve")
    else:
        warn(f"no {cm}")

    proj = ch / "projects"
    if proj.is_dir():
        for folder in sorted(proj.iterdir()):
            idx = folder / "memory" / "MEMORY.md"
            if not idx.is_file():
                continue
            text = idx.read_text(encoding="utf-8", errors="replace")
            dead = [l for l in re.findall(r"\]\(([^)\s#]+\.md)\)", text)
                    if not (idx.parent / l).is_file()]
            key = memory_key(folder.name, h)
            if dead:
                fail(f"memory '{key}': MEMORY.md links to missing files: {', '.join(dead)}")
            else:
                ok(f"memory '{key}': every index link resolves")

    try:
        st = load_state(h)
    except CsbError as e:
        fail(str(e))
        print(f"---- {fails} FAIL(s)")
        return fails
    repo = Path(st["repo_dir"])
    if not (repo / ".git").exists():
        fail(f"backup clone {repo} is missing")
        print(f"---- {fails} FAIL(s)")
        return fails
    try:
        v = visibility(st["remote"])
        if v in ("PRIVATE", "LOCAL") or (v == "UNKNOWN" and st.get("allow_unverified")):
            ok(f"backup remote {st['remote']} is {v.lower()}")
        else:
            fail(f"backup remote {st['remote']} is {v.lower()}; sync will refuse to push")
    except CsbError as e:
        warn(str(e))
    man = read_json(repo / MANIFEST, {}) or {}

    bk = read_json(repo / "claude" / "settings.json")
    live = read_json(ch / "settings.json", {}) or {}
    if bk is not None:
        have = set(hook_commands(live))
        lost = [f"{e}: {c}" for e, c in hook_commands(bk) if (e, c) not in have]
        if lost:
            fail("hooks in the backup but not in settings.json: " + "; ".join(lost))
        else:
            ok(f"settings.json has all {len(hook_commands(bk))} backed-up hooks")
        unset = [k for k in (bk.get("env") or {}) if not (live.get("env") or {}).get(k)]
        if unset:
            warn("env values not set yet: " + ", ".join(sorted(unset)))

    if (repo / "memory").is_dir():
        for key in sorted(p.name for p in (repo / "memory").iterdir() if p.is_dir()):
            if key in man.get("memory_exclude", []):
                continue
            if (ch / "projects" / memory_folder_name(key, h) / "memory").is_dir():
                ok(f"memory '{key}' restored")
            else:
                fail(f"memory '{key}' is in the backup but not on this machine: run sync")

    for r in man.get("repos", []):
        if (h / r["path"] / ".git").exists():
            ok(f"repo ~/{r['path']}")
        else:
            fail(f"repo not cloned: git clone {r['url']} ~/{r['path']}")

    drift = plan(file_map(man, repo, h), repo, st.get("base", {})) if man else []
    if drift:
        warn(f"{len(drift)} file(s) differ from the backup: run sync")
    else:
        ok("this machine matches the backup")
    last = st.get("last_sync")
    if not last:
        warn("never synced")
    else:
        age = datetime.datetime.now() - datetime.datetime.fromisoformat(last)
        if age.days >= STALE_DAYS:
            warn(f"last sync was {age.days} days ago")
        else:
            ok(f"last sync {last}")
    print(f"---- {fails} FAIL(s)")
    return fails


# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="csb.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("init")
    p.add_argument("--remote", required=True)
    p.add_argument("--select", required=True, help="scan --json output, with include flags edited")
    p.add_argument("--dir")
    p.add_argument("--create", action="store_true")
    p.add_argument("--auto-sync", action="store_true")
    p.add_argument("--allow-unverified", action="store_true")
    p = sub.add_parser("sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("-m", "--message")
    p = sub.add_parser("restore")
    p.add_argument("--remote", required=True)
    p.add_argument("--dir")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-unverified", action="store_true")
    p = sub.add_parser("doctor")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("hook")
    p.add_argument("event", choices=["start", "end"])
    a = ap.parse_args(argv)
    h = home()
    try:
        if a.cmd == "scan":
            r = scan(h)
            print(json.dumps(r, indent=2)) if a.json else print_scan(r)
            return 0
        if a.cmd == "init":
            sel = read_json(Path(a.select))
            if sel is None:
                raise CsbError(f"no such file: {a.select}")
            return init(h, a.remote, sel, Path(a.dir) if a.dir else default_repo_dir(h),
                        a.create, a.auto_sync, a.allow_unverified)
        if a.cmd == "sync":
            return sync(h, a.dry_run, a.quiet, a.message)
        if a.cmd == "restore":
            return restore(h, a.remote, Path(a.dir) if a.dir else default_repo_dir(h),
                           a.dry_run, a.allow_unverified)
        if a.cmd == "doctor":
            return min(doctor(h, a.quiet), 125)
        if a.cmd == "hook":
            st = read_json(state_path(h))
            if not st:
                return 0
            man = read_json(Path(st["repo_dir"]) / MANIFEST, {}) or {}
            if not man.get("auto_sync"):
                return 0
            try:
                sync(h, quiet=True, message=f"auto-sync at session {a.event}")
            except CsbError as e:
                print(f"claude-setup-backup: auto-sync skipped: {e}", file=sys.stderr)
            return 0
    except CsbError as e:
        print(f"claude-setup-backup: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
