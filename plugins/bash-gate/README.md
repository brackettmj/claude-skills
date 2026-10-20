# bash-gate

**A hook, not a skill.** It limits the Bash tool to read-only commands in
unattended `claude -p` runs, and it ships a verify script that proves the gate is
live before you trust it.

## Why

You want a scheduled or scripted Claude run to be able to look around: read git
history, check a file's size, syntax-check a script. You don't want it writing,
deleting or reaching the network.

`--allowedTools "Bash(git log:*)"` looks like the answer and isn't. In testing, a
run with one narrow Bash rule still ran other commands, and `mkdir` created a real
directory. Once any Bash rule is present the tool is on, and what gets through is
not predictable from the list.

A PreToolUse hook runs before every Bash call, and the model gets no vote. If the
command isn't on the policy, the call is denied and the model is told why.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install bash-gate@brackettmj-skills
```

Installing changes nothing on its own. The gate only has opinions when
`BASH_GATE` is set, so your interactive sessions behave as before.

Needs `python3` on the PATH that Claude Code's hooks see.

## Use

Check it first, then arm it for the run:

```bash
VERIFY=/path/to/bash-gate/scripts/verify.sh   # /bash-gate:verify prints this path

if bash "$VERIFY"; then
  BASH_GATE=1 claude -p "Check whether last night's backup ran" \
    --allowedTools "Read,Grep,Glob,Bash"
else
  claude -p "Check whether last night's backup ran" \
    --allowedTools "Read,Grep,Glob" --disallowedTools "Bash"
fi
```

The fallback matters. If the gate is broken, the run still happens, without Bash,
instead of with an unguarded one.

## What the default policy allows

`ls`, `pwd`, `wc`, `stat`, `du`, `readlink`, `realpath`, `uname`, `date`,
`bash -n FILE` (syntax check only), and `git` with `log`, `status`, `diff`,
`show`, `rev-parse`, `describe` and `blame`. Everything else is denied.

Some things are denied whatever the policy says, because a policy that allowed
them would leave nothing to gate:

- **Chaining.** `;`, `&`, `|`, `<`, `>`, backticks, `$(` and newlines. Otherwise
  `git log; rm -rf ~` starts with an allowed command.
- **Output flags.** `-o`, `--output`, `--out-file` on any command.
  `git diff --output=FILE` writes a file from an allowed subcommand.
- **Commands that run other commands.** `find` (its `-exec ... {} +` form runs
  anything with no metacharacter to catch), `xargs`, `env`, `sudo`, shells,
  interpreters, `awk`, `sed`, `curl` and others. A policy that lists one is
  rejected, and every call is denied until it's fixed.
- **Escape flags on allowed commands.** `date -s` (sets the clock), `git -c`
  (`core.pager=CMD` runs CMD), `git --exec-path`, `systemctl -H` / `-M` (runs the
  verb on another host or container).
- **Unknown flags before a subcommand.** `systemctl -p status stop x` would read
  `status` as the verb if `-p` were skipped. Unlisted flags in that position are
  denied instead, so a gap in the policy causes a false denial rather than a hole.

## Your own policy

Copy `policy/linux-ops.example.json` (the default plus read-only `systemctl` and
`python3 -m py_compile`), edit it, and point the run at it:

```bash
BASH_GATE=1 BASH_GATE_POLICY=/etc/claude/bash-policy.json claude -p ...
```

Each command gets either `"args": "any"` or a `"subcommands"` list.
`flags_with_value` names flags that take the next token as their value (`git -C
PATH`), `flags_before_subcommand` names the value-less ones allowed before the
verb, and `forbidden_flags` adds denials. `bash` and `python3` only take a
`"mode"`. A policy that fails to load or validate denies every call.

**Keep the policy, and the plugin, somewhere the gated run can't write.** A run
with Write or Edit access to the policy file can widen its own gate. Put the
policy outside the run's working directory, or don't give the run Write.

## Verify

`/bash-gate:verify` in any session, or `scripts/verify.sh` from a script.

- **Quick check** (no flags, no cost). Feeds the gate a denied command and an
  allowed one. Passes only if the denied one exits 2 *and* prints the gate's
  marker, and the allowed one exits 0. Both directions matter: a missing gate
  script also exits 2, because that's what `python3 missing.py` returns, and a
  stub that denies everything would pass a one-sided check.
- **`--live`** (one short headless session, haiku by default). Starts
  `claude -p` with `BASH_GATE=1`, asks it to `touch` a file in a temp directory,
  and checks that the file was never created *and* that the gate's denial showed
  up. The quick check proves the script answers correctly. Only this proves Claude
  Code runs it and honors the denial. If the model never tried the command, it
  reports inconclusive (exit 3) rather than passing.

## What fails open

Claude Code blocks a call when the hook exits 2. Every other non-zero exit is a
non-blocking error, and **the command runs**.

| Failure | Exit | Result |
|---|---|---|
| Command not on the policy | 2 | blocked |
| Error inside the gate | 2 | blocked |
| Broken or missing policy | 2 | blocked |
| Syntax error in `bash-gate.py` | 1 | **runs** |
| No `python3` on the hook's PATH | 127 | **runs** |

The gate can't fix the last two from inside itself, which is why the verify
script exists and why the example above won't hand a run Bash until it passes.

## Known limits

- Commands are matched by name, so `./git` counts as `git`. That's safe while
  the run can't make a file executable. Don't add `chmod` to a policy.
- Short-flag matching is strict. `date -us` is caught as `-s`, and so is
  `date -Iseconds`. Use `date --iso-8601=seconds` instead.
- `python3 -m py_compile` writes a `.pyc` into `__pycache__`. That's the one
  write the example policy accepts.

## Tests

```bash
bash plugins/bash-gate/tests/test-gate.sh     # 90 cases, most of them denials
bash plugins/bash-gate/tests/test-verify.sh   # verify passes a healthy gate and fails 7 broken ones
```
