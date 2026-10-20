#!/usr/bin/env python3
"""PreToolUse gate that limits Bash to read-only commands in unattended runs.

Why this exists
---------------
`--allowedTools "Bash(date:*)"` is not a reliable way to restrict Bash in a
headless `claude -p` run. In testing, a run with that single rule still ran
`uname -a` and created a directory with `mkdir`. Once any Bash rule is present
the tool is on, and what gets through after that is not predictable from the
list.

A PreToolUse hook runs before every Bash call, and the model gets no vote:
exit 2 denies the call and shows stderr to the model as the reason.

Contract
--------
stdin  : the harness's PreToolUse JSON. Only `tool_input.command` is read.
exit 0 : allow.
exit 2 : deny. stderr starts with "bash-gate:", which the verify script checks.

Inert unless armed
------------------
If BASH_GATE is not set in the environment this exits 0 at once, so installing
the plugin does not change interactive sessions. Arm it per run:

    BASH_GATE=1 claude -p "..." --allowedTools "Read,Grep,Glob,Bash"

Fails closed, up to its own process boundary
--------------------------------------------
Any error inside this file denies. But the harness treats every exit code other
than 2 as a NON-blocking error, and the tool call runs. A syntax error here, no
`python3` on the hook's PATH, or a missing file all fail OPEN, silently, in
exactly the unattended session where nobody reads stderr. Nothing in this file
can fix that. scripts/verify.sh can: run it before you hand a session Bash, and
don't hand it Bash if it fails.

What the policy controls, and what it can't
-------------------------------------------
The policy file (policy/default.json, or the path in BASH_GATE_POLICY) lists the
commands a run may use. The checks below the policy are in code on purpose, so
no policy can turn them off:

  * no shell metacharacters (no chaining, pipes, redirects, substitution)
  * no flag that names an output file, on any command
  * no command whose job is running other commands (find, xargs, env, sudo, ...)
  * per-command forbidden flags (date -s, git -c) that apply even if a policy
    leaves them out
"""

import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POLICY = os.path.join(HERE, "..", "policy", "default.json")

# Anything that lets one approved command carry a second, unapproved one.
# `git log; rm -rf ~` starts with an allowed command and is not a git log.
SHELL_METACHARS = re.compile(r"[;&|<>`\n]|\$\(")

# Flags that turn a read-only command into a write, checked on EVERY token. The
# subcommand is not the only place a write hides: `git diff --output=FILE HEAD`
# is an allowed subcommand that creates a file. Costs `ls -o`, which only picks
# a format. Worth losing to keep this rule one line.
WRITE_FLAGS = re.compile(r"^(--output|--out-file|-o)($|=)")

# Commands that exist to run other commands, or that write, or that reach off
# the machine. A policy that allows any of these is rejected as a whole, and
# every call is denied until it is fixed. `find` is the instructive one:
# `find . -maxdepth 0 -exec CMD {} +` runs CMD with no shell metacharacter in
# sight, and -delete and -fprintf write. Whether find is read-only depends on
# its predicates, which an allowlist keyed on the command name can't decide.
# Glob and Grep cover what find would be used for.
NEVER_ALLOW = {
    "find", "xargs", "env", "sudo", "doas", "su", "nohup", "nice", "timeout",
    "time", "watch", "exec", "eval", "command", "builtin", "sh", "dash", "zsh",
    "fish", "ksh", "csh", "tcsh", "perl", "ruby", "node", "awk", "gawk", "mawk",
    "sed", "tee", "dd", "cp", "mv", "rm", "ssh", "scp", "rsync", "curl", "wget",
    "nc", "ncat", "socat", "make", "npm", "npx", "pip", "pip3", "python",
}

# Interpreters that may appear only in a fixed, non-executing mode.
MODES = {
    "bash": "syntax-check",      # bash -n FILE...
    "python3": "py-compile",     # python3 -m py_compile FILE...
}

# Flags denied on these commands whatever the policy says. A policy can add to
# a command's forbidden flags but not remove these.
#   date -s       sets the system clock. Stopped today only by not being root.
#   systemctl -H  runs the verb over ssh; -M runs it in a container.
#   git -c        sets config for one call, and core.pager=CMD runs CMD.
#   git --exec-path, --config-env: the same class of escape.
BUILTIN_FORBIDDEN = {
    "date": ["-s", "--set"],
    "systemctl": ["-H", "--host", "-M", "--machine"],
    "git": ["-c", "--config-env", "--exec-path"],
}


def deny(reason: str) -> None:
    print(f"bash-gate: {reason}", file=sys.stderr)
    sys.exit(2)


def flag_hits(token: str, flag: str) -> bool:
    """Does this argv token use `flag`, in any of the forms a CLI accepts?

    Long flags: `--set` or `--set=VALUE`. Short flags: `-s`, the attached value
    form `-sVALUE`, and a cluster of short flags such as `-us`, which date reads
    as -u plus -s. A cluster match costs some false denials (`git log -Gcache`
    contains a c), which is the cheap direction to be wrong in.
    """
    if flag.startswith("--"):
        return token == flag or token.startswith(flag + "=")
    if token.startswith("--") or not token.startswith("-"):
        return False
    return flag[1] in token[1:]


def load_policy() -> dict:
    """Load and validate the policy. Any problem denies every call."""
    path = os.environ.get("BASH_GATE_POLICY") or DEFAULT_POLICY
    try:
        with open(path, encoding="utf-8") as fh:
            policy = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - fail closed
        deny(f"could not load policy {path} ({exc}). Every Bash call is denied until it loads.")

    commands = policy.get("commands") if isinstance(policy, dict) else None
    if not isinstance(commands, dict) or not commands:
        deny(f"policy {path} has no 'commands' table. Every Bash call is denied.")

    for name, spec in commands.items():
        if not isinstance(spec, dict):
            deny(f"policy {path}: entry '{name}' must be an object.")
        if name in MODES:
            if spec.get("mode") != MODES[name]:
                deny(
                    f"policy {path}: '{name}' runs code, so it is allowed only with "
                    f"\"mode\": \"{MODES[name]}\"."
                )
            continue
        if name in NEVER_ALLOW:
            deny(
                f"policy {path} allows '{name}', which can run other commands, write "
                "files or reach the network. Remove it; every Bash call is denied until then."
            )
        if "mode" in spec:
            deny(f"policy {path}: 'mode' is only valid on {', '.join(sorted(MODES))}.")
        for key in ("forbidden_flags", "flags_with_value", "flags_before_subcommand"):
            flags = spec.get(key, [])
            if not isinstance(flags, list) or not all(
                isinstance(f, str) and len(f) > 1 and f.startswith("-") for f in flags
            ):
                deny(f"policy {path}: '{name}'.{key} must be a list of flags like \"-x\" or \"--long\".")
        has_args = spec.get("args") == "any"
        has_subs = isinstance(spec.get("subcommands"), list) and spec["subcommands"]
        if has_args == bool(has_subs):
            deny(
                f"policy {path}: '{name}' needs exactly one of \"args\": \"any\" or "
                "a non-empty \"subcommands\" list."
            )
    return commands


def check_bash(parts: list) -> None:
    # bash -n means "parse, don't execute". But bash(1) says -n "is ignored by
    # interactive shells", so `bash -i -n -c CMD` executes. Exactly -n plus file
    # paths, nothing else.
    flags = [t for t in parts[1:] if t.startswith("-")]
    if flags != ["-n"]:
        deny("bash is allowed only as `bash -n FILE` (syntax check). -i, -c and -s each execute.")


def check_python(parts: list) -> None:
    # py_compile parses and byte-compiles without running the module. It does
    # write a .pyc into __pycache__, which is the one write this mode accepts.
    # The attached form -mpy_compile is valid Python and denied anyway:
    # strictness is the point.
    flags = [t for t in parts[1:] if t.startswith("-")]
    if flags != ["-m"]:
        deny("python3 is allowed only as `python3 -m py_compile FILE`. -c, -i and script paths execute.")
    rest = [t for t in parts[1:] if not t.startswith("-")]
    if not rest or rest[0] != "py_compile":
        deny("python3 -m is allowed only for py_compile. Every other module runs code.")


def verdict(command: str, commands: dict) -> None:
    """Allow by returning, deny by exiting 2."""
    if not command or not command.strip():
        deny("empty command")

    if SHELL_METACHARS.search(command):
        deny(
            "command contains shell metacharacters (; & | < > ` newline or $( ). "
            "One command per call, no chaining: a chained command can carry an "
            "unapproved one past this gate."
        )

    try:
        parts = shlex.split(command)
    except ValueError as exc:
        deny(f"unparseable command ({exc})")
    if not parts:
        deny("empty command")

    # Identifies a command by NAME, not identity: `./git` reads as `git`. Safe
    # while the run can't make a file executable. If the policy ever allows
    # chmod, or anything else that sets the exec bit, this becomes a hole.
    head = os.path.basename(parts[0])
    if head not in commands:
        deny(f"'{head}' is not in the policy. Allowed: {', '.join(sorted(commands))}.")

    # Before any per-command logic, which returns on the first allowed
    # subcommand and never sees the rest.
    for token in parts:
        if WRITE_FLAGS.match(token):
            deny(f"'{token}' writes a file. No allowed command may name an output path.")

    spec = commands[head]
    forbidden = BUILTIN_FORBIDDEN.get(head, []) + list(spec.get("forbidden_flags", []))
    for token in parts[1:]:
        for flag in forbidden:
            if flag_hits(token, flag):
                deny(f"'{head} {token}' is not read-only. Runs may look at this machine, not change it or reach off it.")

    if head == "bash":
        return check_bash(parts)
    if head == "python3":
        return check_python(parts)

    if spec.get("args") == "any":
        return

    # The first non-flag token is the subcommand. Two rules make that true:
    #   * a flag whose value is a separate token (git -C PATH) swallows the
    #     next token, so a path is never read as the verb. Without this,
    #     `git -C log push` is read as `log` and the push goes through.
    #   * every OTHER flag before the verb must be listed. Skipping unknown
    #     flags would make the verdict depend on flags_with_value being a
    #     complete list of every such flag the command has, which this file
    #     can't check. `systemctl -p status stop UNIT` is that bug. Denying
    #     unknown flags turns a missing entry into a false denial, which
    #     someone notices, instead of a hole nobody does.
    subcommands = set(spec["subcommands"])
    value_flags = set(spec.get("flags_with_value", []))
    preverb_flags = set(spec.get("flags_before_subcommand", []))
    skip_next = False
    for token in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        if token in subcommands:
            return
        if token.startswith("-"):
            base = token.split("=", 1)[0]
            if base in value_flags:
                skip_next = "=" not in token
                continue
            if base in preverb_flags:
                continue
            allowed = ", ".join(sorted(value_flags | preverb_flags)) or "none"
            deny(f"'{head} {token}' is not an allowed option before the subcommand. Allowed: {allowed}.")
        deny(f"'{head} {token}' is not allowed. Subcommands: {', '.join(sorted(subcommands))}.")
    deny(f"'{head}' needs one of: {', '.join(sorted(subcommands))}.")


def main() -> None:
    if not os.environ.get("BASH_GATE"):
        sys.exit(0)

    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001 - fail closed
        deny(f"could not read hook payload ({exc})")
    if not isinstance(payload, dict):
        deny("hook payload is not a JSON object")

    if payload.get("tool_name") not in (None, "Bash"):
        sys.exit(0)

    commands = load_policy()
    command = (payload.get("tool_input") or {}).get("command", "")
    verdict(command, commands)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed
        deny(f"gate crashed ({exc})")
