#!/usr/bin/env bash
# Fail the push if any file carries personal or internal detail.
# Usage: scripts/prepush-scan.sh [dir]   (default: repo root)
# Exit 0 = clean, 1 = hits (printed as file:line), 2 = usage error.
set -uo pipefail

root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
[[ -d "$root" ]] || { echo "prepush-scan: no such dir: $root" >&2; exit 2; }

# Generic checks live here. Personal terms (your name, employers, internal
# project names) go in .prepush-patterns at the repo root, one regex per line,
# and strings allowed through anyway (an author credit) go in .prepush-allow.
# Both files are gitignored, so publishing this script doesn't publish them.
patterns=(
  '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'   # any email address
  '\(?[0-9]{3}\)?[-. ][0-9]{3}[-. ][0-9]{4}'          # US phone number
  '(^|[^0-9])(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]+\.[0-9]+'  # private IPv4
  '/home/|/Users/|C:\\Users'                        # home paths
  'sk-or-v1|sk-ant-|AKIA[0-9A-Z]{12}'                 # key prefixes
)
readlines() { [[ -f "$1" ]] && grep -vE '^\s*(#|$)' "$1" || true; }
pfile="${PREPUSH_PATTERNS:-$root/.prepush-patterns}"
afile="${PREPUSH_ALLOW:-$root/.prepush-allow}"
if [[ -f "$pfile" ]]; then
  mapfile -t -O "${#patterns[@]}" patterns < <(readlines "$pfile")
else
  echo "prepush-scan: warning: no $pfile, generic checks only" >&2
fi
allow="$(readlines "$afile" | paste -sd'|')"
re="$(IFS='|'; echo "${patterns[*]}")"

hits=0
while IFS= read -r -d '' f; do
  grep -Iq . "$f" 2>/dev/null || continue   # skip binaries and empty files
  while IFS= read -r line; do
    n="${line%%:*}"; text="${line#*:}"
    stripped="$text"; [[ -n "$allow" ]] && stripped="$(sed -E "s/${allow}//g" <<<"$text")"
    if grep -qiE -- "$re" <<<"$stripped"; then
      echo "${f#"$root"/}:$n: $text"; hits=$((hits+1))
    fi
  done < <(grep -n '' "$f")
done < <(find "$root" -type f -not -path '*/.git/*' \
           -not -name 'prepush-scan.sh' \
           -not -name '.prepush-patterns' -not -name '.prepush-allow' -print0)

if (( hits )); then echo "prepush-scan: $hits hit(s). Fix by amending, not a cleanup commit." >&2; exit 1; fi
echo "prepush-scan: clean"
