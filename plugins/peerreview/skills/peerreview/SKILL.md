---
name: peerreview
description: Get an independent review of a finished document, report, plan or diff from a non-Anthropic model (GPT, Gemini and others via OpenRouter), then reconcile the findings. Use when the user asks for a peer review, second opinion, cross-model check or fact-check from another model, or wants a document verified before it ships. Shows the cost before spending, and spending is capped by a local budget jar.
---

# Peer review from another model family

A review by another Claude shares most of Claude's blind spots. This skill sends the
document to a model from a different lab through OpenRouter, so its mistakes are less
likely to overlap with yours. Different families tend to catch different defect classes.
In one comparison, a same-family pass caught wrong facts while a GPT pass caught broken
reasoning, and the two lists barely overlapped. Use it on finished work, not drafts.

The script is `scripts/peerreview.py` next to this file (stdlib Python, no install).
It needs `OPENROUTER_API_KEY` in the environment. If the key is missing, tell the user
to create one at https://openrouter.ai/keys and export it. Don't ask them to paste it
into the chat.

## Steps

**1. Plan first. It sends nothing.**

```
python3 <skill dir>/scripts/peerreview.py DOCUMENT --plan
```

Show the user the model, the estimated cost (an upper bound, with output priced at the
cap) and what's left in the jar. If the plan says WILL STOP or shows CONTENT SWEEP hits,
stop and say why.

**2. Run it.** Inside the jar and under the per-call cap, run it without asking again:

```
python3 <skill dir>/scripts/peerreview.py DOCUMENT -o /tmp/peerreview-findings.md
```

Useful flags: `--model ID` (default `openai/gpt-5.1`, or `$PEERREVIEW_MODEL`),
`--rubric FILE` to swap the built-in fact-check rubric for the user's own,
`--context FILE` for reference material the reviewer reads but doesn't grade.

Use `--context` sparingly. Reviewers sometimes blame the document for things that are
only in the reference file. Leave context out unless the document can't be judged
without it.

**3. Reconcile. Don't paste the raw output.** Read every finding against the document
and sort it:

- **Confirmed.** You checked it and it's right. Say what to change.
- **False positive.** Quote what the reviewer missed (the caveat it overlooked, the
  number it misread). Common causes: the document already discloses the gap, the
  claim is in a `--context` file, or the reviewer doesn't recognize something newer
  than its training data.
- **Unverifiable here.** Needs a live source. Say what would settle it.

Lead with the confirmed findings, in severity order. Report what the review cost
(the script prints it, along with the jar balance).

## Spending rules

- Never pass `--approve` on your own. It bypasses the jar, the per-call cap and the
  content sweep. Use it only when the user says yes to that specific call.
- The content sweep blocks keys, tokens, emails, phone numbers and account numbers
  before anything leaves the machine. Treat a hit as real until the user says it's
  benign.
- Don't send anything the user marked confidential, whatever the sweep says. The
  document goes to a third-party API.
- `--jar` shows the balance. `--ledger` shows every call so far. The jar lives in
  `~/.config/peerreview/budget.json` ($2.00 total, $0.50 per call by default). The
  user edits that file to change the limits.
