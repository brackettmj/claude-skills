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

## Contributing

Issues and PRs welcome. Run `scripts/prepush-scan.sh` before you push; it fails on
emails, phone numbers, private IPs, home paths and API key prefixes.

MIT licensed.
