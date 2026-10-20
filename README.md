# claude-skills

Claude Code skills and plugins from incident management and ops work. Each one
installs on its own.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install <name>@brackettmj-skills
```

## What's here

| Plugin | What it does |
|---|---|
| [postmortem](plugins/postmortem) | Blameless postmortems built from evidence. Every interval names its start and stop, every why-ladder ends at something you own or an honest "unknown," and action items count as done only when they're durable. [See an example.](plugins/postmortem/examples/checkout-503s.md) |
| [peerreview](plugins/peerreview) | Sends a finished document to a model from another lab (GPT, Gemini, others via OpenRouter) for an independent fact-check, then has Claude sort the findings into confirmed, false positive and unverifiable. Shows the cost first; a local budget jar caps spend. |
| [plain-writing](plugins/plain-writing) | Writing that reads like a person wrote it. Draft mode writes to a plain-language rulebook; review mode marks each AI tell (filler, buzzwords, hedging, wrap-ups) with the fix. [See a before and after.](plugins/plain-writing/examples/before-after.md) |
| [bash-gate](plugins/bash-gate) | **A hook, not a skill.** Limits Bash to a read-only policy in unattended `claude -p` runs, because `--allowedTools` patterns don't. A verify script proves the gate is live, end to end, before you hand a run Bash. Off unless `BASH_GATE` is set. |
| [memory-audit](plugins/memory-audit) | Audits a Claude Code memory folder: memories missing from the index but still recallable, dead index lines, broken `[[links]]`, bad frontmatter, paths that no longer exist, and memories that may just copy a file. Reports only; you pick the fixes. |

## Contributing

Issues and PRs welcome. Run `scripts/prepush-scan.sh` before you push; it fails on
emails, phone numbers, private IPs, home paths and API key prefixes.

MIT licensed.
