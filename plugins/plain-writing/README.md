# plain-writing

Writing that reads like a person wrote it, not a model.

The rulebook is short: cut hype and throat-clearing, swap a dozen overused words for
plain ones, stop hedging, skip the wrap-up paragraph, lead with the answer, be
concrete. The skill applies it two ways.

- **Draft:** writes new text to the rules, puts the point first, and leaves a marked
  gap like `[owner]` where a fact is missing instead of covering it with a vague phrase.
- **Review:** marks each tell in existing text with its category and a plain fix,
  ordered by impact, then names the one or two habits that show up most. It doesn't
  rewrite unless asked, so the writer learns the pattern.

**Example:** [before-after.md](examples/before-after.md) runs a fictional status
update through both modes.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install plain-writing@brackettmj-skills
```

Then ask: "make this sound less like AI" or "review this email for fluff."

The rulebook is in [`skills/plain-writing/references/rules.md`](skills/plain-writing/references/rules.md).
It's useful on its own as a self-edit checklist.

## What it isn't

Not an AI detector. It can't tell you whether a model wrote something, and it won't
claim to. Not a grammar checker either.
