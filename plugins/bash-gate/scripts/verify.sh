#!/usr/bin/env bash
# Is the bash gate actually live? Run this before handing an unattended session
# a Bash tool, and don't hand it one if this fails.
#
#   verify.sh          preflight: the gate script denies, allows, and is ours
#   verify.sh --live   also start a real headless claude session with the gate
#                      armed and check that Claude Code blocks a command
#
# Exit 0 = gate live. 1 = gate broken, do not arm Bash. 3 = --live was
# inconclusive (the model never tried the command), so nothing was proven.
#
# Why both directions: a missing gate script still exits 2, because
# `python3 /no/such/file` exits 2, which is the same code as "denied". So a deny
# alone proves nothing. The preflight needs exit 2 AND the "bash-gate:" marker
# on a denied command, AND exit 0 on an allowed one. That last part catches a
# stub that denies everything.
#
# Env:
#   GATE              gate script to check (default: the one next to this file)
#   BASH_GATE_POLICY  policy to check against (default: the plugin's default)
#   ALLOW_PROBE       a command your policy allows (default: pwd)
#   CLAUDE_BIN        claude binary for --live (default: claude)
#   LIVE_MODEL        model for --live (default: haiku; one short turn)

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="${GATE:-$HERE/bash-gate.py}"
ALLOW_PROBE="${ALLOW_PROBE:-pwd}"

payload() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$1"
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL  python3 is not on PATH. The hook can't run, and a hook that can't run lets every command through."
  exit 1
fi

deny_err="$(payload 'rm -rf /nonexistent-bash-gate-probe' | BASH_GATE=1 python3 "$GATE" 2>&1 >/dev/null)"; deny_rc=$?
allow_err="$(payload "$ALLOW_PROBE" | BASH_GATE=1 python3 "$GATE" 2>&1 >/dev/null)"; allow_rc=$?
marker=no; [[ "$deny_err" == bash-gate:* ]] && marker=yes

if [[ $deny_rc -ne 2 || $marker != yes ]]; then
  echo "FAIL  denied command: exit $deny_rc, marker $marker (want exit 2 and marker yes)"
  [[ -n "$deny_err" ]] && echo "      ${deny_err%%$'\n'*}"
  exit 1
fi
if [[ $allow_rc -ne 0 ]]; then
  echo "FAIL  allowed command '$ALLOW_PROBE': exit $allow_rc (want 0)"
  [[ -n "$allow_err" ]] && echo "      ${allow_err%%$'\n'*}"
  exit 1
fi
echo "ok    gate script: denies with its marker, allows '$ALLOW_PROBE' ($GATE)"

[[ "${1:-}" == "--live" ]] || exit 0

# The preflight proves the script answers correctly. It can't prove Claude Code
# runs the script and honors exit 2. Only a real session can.
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "FAIL  --live needs the claude CLI on PATH (or set CLAUDE_BIN)"
  exit 1
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
target="$work/gate-probe"
echo "...   live: starting a headless session with BASH_GATE=1 (about 15 seconds)"
out="$(cd "$work" && BASH_GATE=1 "$CLAUDE_BIN" -p \
  "Use the Bash tool to run exactly this command, once, and nothing else: touch $target
If it is refused, do not retry or work around it. Reply with one word: done." \
  --model "${LIVE_MODEL:-haiku}" \
  --allowedTools "Bash" \
  --output-format stream-json --verbose 2>&1 </dev/null)"

# What the session did, for a FAIL: which plugins loaded, which tool ran, and
# what came back. "Not proven" is no use to someone trying to fix it.
diagnose() {
  python3 -c '
import json, sys
for line in sys.stdin:
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("type") == "system" and e.get("subtype") == "init":
        names = [p.get("name") for p in e.get("plugins", [])]
        print("      plugins loaded:", ", ".join(names) or "none")
    content = (e.get("message") or {}).get("content")
    for c in content if isinstance(content, list) else []:
        if c.get("type") == "tool_use":
            print("      tool call:", c.get("name"), json.dumps(c.get("input"))[:150])
        elif c.get("type") == "tool_result":
            print("      result:", str(c.get("content"))[:200].replace("\n", " "))
' <<<"$out"
  echo "      claude: $(command -v "$CLAUDE_BIN")  python3: $(command -v python3)  BASH_GATE_POLICY: ${BASH_GATE_POLICY:-default}"
}

if [[ -e "$target" ]]; then
  echo "FAIL  live: the session created $target. Claude Code did not run the gate, or ran it and let the call through."
  echo "      Is the bash-gate plugin installed and enabled for this config?"
  diagnose
  exit 1
fi
if ! grep -q 'bash-gate:' <<<"$out"; then
  echo "INCONCLUSIVE  live: nothing was created, but the gate's denial never showed up either."
  diagnose
  echo "      The model may not have tried the command. Nothing was proven; run it again."
  exit 3
fi
echo "ok    live: Claude Code ran the gate and blocked the command"
