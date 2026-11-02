# postmortem

A skill that writes blameless incident postmortems from evidence, not memory.

Most postmortems fail in the same few places: "took 3 hours to fix" with no start or
stop, a root cause that ends at "human error," action items like "be more careful."
This skill won't accept any of those. It asks for the record first (chat logs,
alerts, deploy log), builds the clock, runs a Five Whys chain per symptom, and writes
action items with an owner, a type and a tracking link.

It also reviews postmortems someone else wrote.

**Example output:** [checkout-503s.md](examples/checkout-503s.md), a fictional outage
run through every section.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install postmortem@brackettmj-skills
```

Then ask: "write a postmortem for last night's checkout outage" or "review this RCA."

## What it holds you to

- Every interval names what starts and stops it.
- Impact in your units (requests, orders, jobs), with attempted / failed / rate.
- Each Five Whys chain ends at a root cause you own, or at "unknown, stopped because
  ___." Every why follows from the answer above it; a sibling cause gets its own chain.
  Five deep where the evidence goes, fewer when it truly closes, never padded.
- Four chains always run: how it shipped, why testing missed it, why diagnosis took
  as long as it did, why it spread.
- Blameless: people appear as participants and owners, never as causes.
- Done means durable: in code, config, the runbook or the tracker.

The full template is in [`skills/postmortem/references/template.md`](skills/postmortem/references/template.md).
