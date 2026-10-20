# Postmortem template

Blameless. Works for a production outage, a failed launch, or a broken home lab.
Delete the guidance lines as you fill it in.

---

# <Title: what failed, in plain words>

**Summary (3–4 sentences).** What broke, who it hit, the root cause, what fixed it,
how we know the fix holds.

## 1. Clock

Name what starts and stops every interval. Never write a bare "time to fix."

| Event | Time | Source |
|---|---|---|
| Project/change start (if this was a launch) | | |
| First failure | | |
| Detected (and by what: tool, human, customer) | | |
| Correct diagnosis | | |
| Mitigation deployed | | |
| Fix verified | | |

| Interval | Value |
|---|---|
| End to end (start → verified) | |
| Time to detect | |
| Time to correct diagnosis | |
| Time to mitigate | |

## 2. Impact

- **Baseline:** was there a working service to lose (outage) or not (failed launch)?
- **By unit:** requests, jobs/batches (what the user was actually trying to do), users,
  minutes. Give attempted / failed / rate for each. Partial-by-request can be
  total-by-job.
- **Blast radius:** did one failure take down things after it (queues, retries)?

## 3. Who was involved

Every investigator, human and agent, with where their record lives. Pull each
record before writing. A session not in the record is half the story missing.

## 4. Timeline

Times, events, and the evidence that drove each decision. Mark guesses with `~`.

## 5. Root cause: the whys

One numbered ladder per symptom (Chain A, B, …). Each why ends at one of two bottoms:

- **A decision or gap we own and can change**, or
- **"Unknown — stopped because ___."** Stopping is fine. Not saying why you stopped
  is not.

"It didn't work" is never a bottom. Ask the next why.

Always run these chains, even when the mechanism is obvious:
- **How did it get shipped?** (capacity, review, design)
- **Why didn't testing catch it?** (did the test force the failure condition?)
- **Why did diagnosis take as long as it did?** (where did the evidence live?)
- **Why did one failure spread?** (cancel paths, queues, retries)

## 6. Controls still in place

Every mitigation still running, including ones that "didn't work." For each:
proven to matter / unproven (schedule a test) / proven useless (remove it).

## 7. Counter-evidence

What doesn't fit the story. Outliers, unverified assumptions, data we couldn't get.

## 8. What went well, what didn't

A workaround that went well can still point at a gap. File the gap too.

## 9. Action items

| # | Item | Chain | Type | Owner | Tracking |
|---|---|---|---|---|---|
| | | A | fix / detect / mitigate / prevent / verify / record | | board link |

**Done means durable:** in the tool, the config, or the board. A shell loop, a
memory note, or "we'll remember" is not Done.
