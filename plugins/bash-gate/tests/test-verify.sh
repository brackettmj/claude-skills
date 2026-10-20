#!/usr/bin/env bash
# Tests for verify.sh's preflight: it must pass a healthy gate and fail every
# broken one, including the two that a single "did it exit 2?" check passes.
#
# Run:  bash plugins/bash-gate/tests/test-verify.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY="$HERE/../scripts/verify.sh"
REAL="$HERE/../scripts/bash-gate.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

# $1 name, $2 expected exit, then env assignments for verify.sh
check() {
  local name="$1" want="$2"; shift 2
  local out rc
  out="$(env -u BASH_GATE_POLICY "$@" "$BASH" "$VERIFY" 2>&1)"; rc=$?
  if [[ $rc -ne $want ]]; then
    printf 'FAIL  %-40s expected exit %d, got %d: %s\n' "$name" "$want" "$rc" "$out"; fail=$((fail+1)); return
  fi
  printf 'ok    %-40s exit %d\n' "$name" "$rc"
  pass=$((pass+1))
}

printf 'x = (\n' >"$TMP/syntax.py"
printf 'import sys; sys.exit(0)\n' >"$TMP/allow-all.py"
# Denies everything and forges the marker. Probe 1 alone would call it healthy.
printf 'import sys; print("bash-gate: no", file=sys.stderr); sys.exit(2)\n' >"$TMP/deny-all.py"

check "healthy gate"                   0 GATE="$REAL"
check "missing gate (python exits 2)"  1 GATE="$TMP/does-not-exist.py"
check "syntax error"                   1 GATE="$TMP/syntax.py"
check "allow-everything stub"          1 GATE="$TMP/allow-all.py"
check "deny-everything, forged marker" 1 GATE="$TMP/deny-all.py"
check "probe not in policy"            1 GATE="$REAL" ALLOW_PROBE="hostname"
check "broken policy"                  1 GATE="$REAL" BASH_GATE_POLICY="$TMP/nope.json"
check "no python3 on PATH"             1 GATE="$REAL" PATH="/nonexistent"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
