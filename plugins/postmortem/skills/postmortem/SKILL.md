---
name: postmortem
description: Write a blameless incident postmortem (RCA, COE, incident review) from evidence. Use when the user asks for a postmortem, root cause analysis, incident write-up or retro on an outage, failed deploy, failed launch or anything that broke, or wants an existing postmortem reviewed. Interviews for the facts, builds the clock and the why-ladders, and ends with owned action items and a short exec summary.
---

# Postmortem

A postmortem is worth what its evidence is worth. Your job is to get the facts out of
the user and their records, then hold the write-up to the rules below. Don't draft from
a summary of what people remember. If you can't fill a field, write that it's unknown and why.

The full template is in `references/template.md`. Read it before you start writing.

## How to run it

**1. Collect the record before you write anything.** Ask what exists: chat or bridge
logs, the ticket, alert history, deploy log, dashboards, agent session transcripts.
If the user can paste or point you at them, read them. Every person or agent who worked
the incident goes on the list in section 3. A session that isn't in the record is half
the story missing.

**2. Build the clock.** Get a timestamp and a source for each event in the template's
clock table. Then compute the intervals. Every interval names its start and its stop.
"Took 3 hours to fix" is not allowed: 3 hours from what to what? Detection gets a
"by what": a monitor, a human, a customer. A customer detecting it is a finding.

**3. Size the impact in the user's units.** Requests, jobs, orders, users, minutes:
attempted, failed, rate. Watch for the case where a small per-request failure rate was
a total failure per job. Say whether there was a working service to lose. A failed
launch and an outage are different stories.

**4. Ask the whys, one ladder per symptom.** Each ladder ends at one of two bottoms:
- a decision or gap the team owns and can change, or
- "Unknown, stopped because ___."

"It didn't work," "human error" and "the vendor was down" are never bottoms. Ask the
next why: why could one person's mistake reach production, why did the vendor outage
take us down with it? Always run the four standing chains from the template (how it
shipped, why testing missed it, why diagnosis took as long as it did, why it spread),
even when the mechanism is obvious.

**5. Look for what doesn't fit.** Outliers, assumptions nobody checked, data you
couldn't get. List them in counter-evidence. A clean story with no loose ends usually
means nobody looked for any.

**6. Write action items that close.** Each one links to a ladder, has a type
(fix / detect / mitigate / prevent / verify / record), an owner who is a person, and a
tracking link or a placeholder flagged for the user to fill. Done means durable: in
the code, the config, the runbook or the tracker. "We'll remember" and "be more careful"
are not action items.

**7. Write the summary last.** Three or four sentences at the top: what broke, who it
hit, the root cause, what fixed it, how we know the fix holds. Then offer a 4-line exec
version for leadership: impact, cause, fix, the one action item that matters most.

## Rules that hold the whole way through

- **Blameless.** Name roles and systems, not people, when describing what went wrong.
  People appear in section 3 (who was involved) and as action-item owners. Nowhere else.
- **Mark guesses.** A time or number you inferred gets a `~`. A cause you suspect but
  can't prove goes in counter-evidence, not the root-cause ladder.
- **Ask before inventing.** If a field needs a fact you don't have, ask for it. If the
  user doesn't know, write "unknown" with the reason, then move on.
- **Plain words.** The title says what failed ("Checkout returned 503s for 41 minutes
  after a cache config change"), not "Service Degradation Event."

## Reviewing an existing postmortem

When asked to review one instead of writing it, check it against the steps above and
report what's missing or weak in order of severity: intervals without a named start
and stop, ladders that stop at "human error," action items without an owner or that
aren't durable, impact with no units, and a summary that hides the cause. Quote the
line you're pointing at and say what would fix it.
