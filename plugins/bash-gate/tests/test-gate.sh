#!/usr/bin/env bash
# Fixture tests for bash-gate.py.
#
# The point is the DENY paths. A permission gate that has never been watched to
# refuse anything is worse than no gate at all, because it reads like
# protection.
#
# Run:  bash plugins/bash-gate/tests/test-gate.sh
# Exits 0 if every path behaved as specified, 1 otherwise.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="${GATE:-$HERE/../scripts/bash-gate.py}"
EXAMPLE="$HERE/../policy/linux-ops.example.json"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

# A gate that doesn't compile exits 1, and exit 1 is a NON-blocking hook error:
# the tool call runs. Say that once, up front, instead of 90 confusing failures.
if ! python3 -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$GATE"; then
  echo "FAIL  bash-gate.py does not compile. It would fail OPEN, not closed."
  exit 1
fi

# $1 name, $2 allow|deny, $3 command, $4 BASH_GATE value ("" = unset), $5 policy ("" = default)
probe() {
  local name="$1" expect="$2" cmd="$3" armed="${4-1}" policy="${5-}"
  local payload rc out
  payload="$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$cmd")"
  local -a envs=(env -u BASH_GATE -u BASH_GATE_POLICY)
  [[ -n "$armed" ]] && envs+=("BASH_GATE=$armed")
  [[ -n "$policy" ]] && envs+=("BASH_GATE_POLICY=$policy")
  out="$(printf '%s' "$payload" | "${envs[@]}" python3 "$GATE" 2>&1)"; rc=$?
  local got="allow"; [[ $rc -eq 2 ]] && got="deny"
  if [[ $rc -ne 0 && $rc -ne 2 ]]; then
    printf 'FAIL  %-46s unexpected exit %d: %s\n' "$name" "$rc" "$out"; fail=$((fail+1)); return
  fi
  if [[ "$got" != "$expect" ]]; then
    printf 'FAIL  %-46s expected %s, got %s  %s\n' "$name" "$expect" "$got" "$out"; fail=$((fail+1)); return
  fi
  if [[ $got == deny && "$out" != bash-gate:* ]]; then
    printf 'FAIL  %-46s denied without the bash-gate: marker: %s\n' "$name" "$out"; fail=$((fail+1)); return
  fi
  printf 'ok    %-46s %s\n' "$name" "$got"
  pass=$((pass+1))
}

probe_raw() {
  local name="$1" expect="$2" stdin="$3" rc out got
  out="$(printf '%s' "$stdin" | env -u BASH_GATE_POLICY BASH_GATE=1 python3 "$GATE" 2>&1)"; rc=$?
  got="allow"; [[ $rc -eq 2 ]] && got="deny"
  if [[ "$got" != "$expect" ]]; then
    printf 'FAIL  %-46s expected %s, got %s  %s\n' "$name" "$expect" "$got" "$out"; fail=$((fail+1)); return
  fi
  printf 'ok    %-46s %s\n' "$name" "$got"
  pass=$((pass+1))
}

echo "--- read-only observation the default allows ---"
probe "bash -n on a script"              allow "bash -n /tmp/x.sh"
probe "git log"                          allow "git log --oneline -5"
probe "stat a file"                      allow "stat /etc/hostname"
probe "ls -la"                           allow "ls -la /tmp"
probe "du -sh"                           allow "du -sh /tmp"
probe "ls -s (date's -s rule is scoped)" allow "ls -s /tmp"
probe "date -u"                          allow "date -u"
probe "date +FORMAT"                     allow "date +%s"
probe "date --iso-8601=seconds"          allow "date --iso-8601=seconds"

echo "--- writes that got past --allowedTools in testing ---"
probe "mkdir"                            deny  "mkdir -p /tmp/scope-probe-dir"
probe "touch"                            deny  "touch /tmp/x"
probe "rm -rf"                           deny  "rm -rf /tmp/x"

echo "--- chaining: an allowed head carrying a denied tail ---"
probe "git log ; rm -rf"                 deny  "git log ; rm -rf /tmp/x"
probe "git log && curl"                  deny  "git log && curl https://example.com"
probe "date | sh"                        deny  "date | sh"
probe "command substitution"             deny  "stat \$(curl -s https://evil.example)"
probe "backticks"                        deny  'stat `whoami`'
probe "redirect to a file"               deny  "date > /tmp/x"
probe "newline-smuggled second line"     deny  "date
rm -rf /tmp/x"

echo "--- write verbs of allowed commands ---"
probe "git push"                         deny  "git push origin main"
probe "git commit"                       deny  "git commit -m x"
probe "bash without -n (executes)"       deny  "bash /tmp/x.sh"
probe "systemctl not in the default"     deny  "systemctl status cron"
probe "python3 not in the default"       deny  "python3 -m py_compile x.py"

echo "--- execution primitives and output flags ---"
probe "find -exec, + form, no metachars" deny  "find /tmp -maxdepth 0 -exec rm -rf /tmp/x {} +"
probe "find -delete"                     deny  "find /tmp -name x -delete"
probe "git diff --output= writes"        deny  "git diff --output=/tmp/x HEAD"
probe "bash -i -n -c (i defeats n)"      deny  "bash -i -n -c 'rm -rf /tmp/x'"
probe "bash -n -c"                       deny  "bash -n -c 'rm -rf /tmp/x'"
probe "bash -n plus an rcfile"           deny  "bash -n --rcfile /tmp/evil /tmp/x.sh"

echo "--- flags that escape read-only without changing the verb ---"
probe "date -s sets the clock"           deny  "date -s ''"
probe "date --set= same thing"           deny  "date --set=2020-01-01"
probe "date -us (clustered -s)"          deny  "date -us 2020-01-01"
probe "date -s2020 (attached value)"     deny  "date -s2020-01-01"
probe "git -c config injection"          deny  "git -c core.pager=sh log"
probe "git -c attached form"             deny  "git -ccore.pager=sh log"
probe "git --config-env"                 deny  "git --config-env=core.pager=VAR log"
probe "git --exec-path"                  deny  "git --exec-path=/tmp log"

echo "--- flags that take a separate value ---"
probe "git -C path log"                  allow "git -C /tmp/repo log --oneline -5"
probe "git -C path push still denies"    deny  "git -C /tmp/repo push"
probe "git -C VERB smuggles push"        deny  "git -C log push"
probe "git -C log status is legitimate"  allow "git -C log status"
probe "git --git-dir spaced"             allow "git --git-dir /tmp/repo/.git log"
probe "git --git-dir attached push"      deny  "git --git-dir=/tmp/repo/.git push"
probe "git -C plus --output still writes" deny "git -C /tmp diff --output=/tmp/x HEAD"
probe "unknown git pre-verb flag"        deny  "git --super-prefix log push"
probe "git --no-pager with -C"           allow "git --no-pager -C /tmp/repo log -1"

echo "--- example policy: systemctl and python3 ---"
probe "systemctl --user list-timers"     allow "systemctl --user list-timers" 1 "$EXAMPLE"
probe "systemctl --user status ok"       allow "systemctl --user status cron.timer" 1 "$EXAMPLE"
probe "show -p after the verb"           allow "systemctl --user show x.timer -p LastTriggerUSec" 1 "$EXAMPLE"
probe "systemctl start"                  deny  "systemctl --user start x.timer" 1 "$EXAMPLE"
probe "systemctl daemon-reload"          deny  "systemctl --user daemon-reload" 1 "$EXAMPLE"
probe "systemctl --host runs over ssh"   deny  "systemctl --host=build-box.example.com status x" 1 "$EXAMPLE"
probe "systemctl -H short form"          deny  "systemctl -H build-box.example.com status x" 1 "$EXAMPLE"
probe "systemctl -M container"           deny  "systemctl -M box status x" 1 "$EXAMPLE"
probe "systemctl -p VERB smuggles"       deny  "systemctl -p status list-jobs" 1 "$EXAMPLE"
probe "smuggled --user stop"             deny  "systemctl --user -p status stop x.service" 1 "$EXAMPLE"
probe "smuggled poweroff"                deny  "systemctl --user -p status poweroff" 1 "$EXAMPLE"
probe "unknown systemctl pre-verb flag"  deny  "systemctl --nonsense status x" 1 "$EXAMPLE"
probe "py_compile a file"                allow "python3 -m py_compile $GATE" 1 "$EXAMPLE"
probe "python3 -c executes"              deny  "python3 -c 'print(1)'" 1 "$EXAMPLE"
probe "bare script path executes"        deny  "python3 script.py" 1 "$EXAMPLE"
probe "another -m module runs code"      deny  "python3 -m http.server" 1 "$EXAMPLE"
probe "attached -mpy_compile form"       deny  "python3 -mpy_compile x.py" 1 "$EXAMPLE"
probe "-i smuggled alongside -m"         deny  "python3 -i -m py_compile x.py" 1 "$EXAMPLE"
probe "-c smuggled after py_compile"     deny  "python3 -m py_compile -c print(1)" 1 "$EXAMPLE"
probe "bare python3 is a REPL"           deny  "python3" 1 "$EXAMPLE"
probe "python (not python3)"             deny  "python -c 'print(1)'" 1 "$EXAMPLE"

echo "--- a policy can't switch off the checks in code ---"
cat >"$TMP/find.json" <<'EOF'
{"commands": {"ls": {"args": "any"}, "find": {"args": "any"}}}
EOF
cat >"$TMP/bash-free.json" <<'EOF'
{"commands": {"bash": {"args": "any"}}}
EOF
cat >"$TMP/date-nofilter.json" <<'EOF'
{"commands": {"date": {"args": "any"}, "git": {"subcommands": ["log"]}}}
EOF
cat >"$TMP/narrow.json" <<'EOF'
{"commands": {"ls": {"args": "any"}, "wc": {"args": "any", "forbidden_flags": ["--files0-from"]}}}
EOF
cat >"$TMP/both.json" <<'EOF'
{"commands": {"git": {"args": "any", "subcommands": ["log"]}}}
EOF
cat >"$TMP/badflags.json" <<'EOF'
{"commands": {"ls": {"args": "any", "forbidden_flags": "-x"}}}
EOF
printf 'not json' >"$TMP/broken.json"
probe "find in a policy denies everything" deny "ls /tmp"                 1 "$TMP/find.json"
probe "bash with free args is rejected"  deny  "bash -n /tmp/x.sh"        1 "$TMP/bash-free.json"
probe "date -s denied without a policy rule" deny "date -s ''"            1 "$TMP/date-nofilter.json"
probe "git -c denied without a policy rule"  deny "git -c core.pager=sh log" 1 "$TMP/date-nofilter.json"
probe "custom policy allows its own"     allow "ls /tmp"                  1 "$TMP/narrow.json"
probe "custom policy narrows (git gone)" deny  "git log"                  1 "$TMP/narrow.json"
probe "policy forbidden_flags apply"     deny  "wc --files0-from=/tmp/x"  1 "$TMP/narrow.json"
probe "output flag still denied"         deny  "ls -o /tmp"               1 "$TMP/narrow.json"
probe "args AND subcommands rejected"    deny  "git log"                  1 "$TMP/both.json"
probe "forbidden_flags as a string"      deny  "ls /tmp"                  1 "$TMP/badflags.json"
probe "unparseable policy denies"        deny  "ls /tmp"                  1 "$TMP/broken.json"
probe "missing policy denies"            deny  "ls /tmp"                  1 "$TMP/nope.json"

echo "--- absolute paths don't dodge the name check ---"
probe "/usr/bin/rm"                      deny  "/usr/bin/rm -rf /tmp/x"
probe "/usr/bin/git log"                 allow "/usr/bin/git log --oneline -1"

echo "--- fail closed ---"
probe_raw "malformed JSON"               deny  "not json at all"
probe_raw "empty stdin"                  deny  ""
probe_raw "JSON that isn't an object"    deny  "[1,2]"
probe "empty command string"             deny  ""
probe "unparseable quoting"              deny  "stat 'unclosed"

echo "--- inert unless armed ---"
probe "rm -rf with BASH_GATE unset"      allow "rm -rf /tmp/x" ""
probe "curl with BASH_GATE unset"        allow "curl https://example.com" ""
probe "broken policy, unarmed"           allow "ls /tmp" "" "$TMP/broken.json"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
