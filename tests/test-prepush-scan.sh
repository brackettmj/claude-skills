#!/usr/bin/env bash
# Prove the scanner can go red, one planted defect per pattern class.
set -u
here="$(cd "$(dirname "$0")" && pwd)"; scan="$here/../scripts/prepush-scan.sh"
fx="$here/fixtures"; pass=0; fail=0
check() { # name, dir, want_rc
  "$scan" "$2" >/dev/null 2>&1; rc=$?
  if [[ $rc == "$3" ]]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $1: rc=$rc want $3"; fi
}
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Stand-ins for a user's private files: one secret term, one allowed credit.
export PREPUSH_PATTERNS="$tmp/patterns" PREPUSH_ALLOW="$tmp/allow"
printf '%s\n' '# private terms' 'zorblax' 'example' > "$PREPUSH_PATTERNS"
printf '%s\n' 'Jane Q\. Example' > "$PREPUSH_ALLOW"
planted=(
  "email:reach me at someone""@example.org"
  "phone:call (555) 555""-0142"
  "ip:host at 10.20"".30.40"
  "path:see /ho""me/someone/notes"
  "private-term:the Zorblax migration"
  "allow-partial:Jane Q. Example is fine but Example alone is not"
  "key:sk-""ant-abc123"
)
for p in "${planted[@]}"; do
  name="${p%%:*}"; mkdir -p "$tmp/$name"; echo "${p#*:}" > "$tmp/$name/f.md"
  check "$name" "$tmp/$name" 1
done
check clean   "$fx/clean"   0
check allowed "$fx/allowed" 0
check missing-dir "$tmp/nope" 2
echo "$pass passed, $fail failed"; (( fail == 0 ))
