# peerreview

A second opinion on a finished document from a model that isn't Claude.

When Claude checks Claude's work, both share most of their blind spots. This skill
sends the document to a model from another lab through [OpenRouter](https://openrouter.ai),
then has Claude go through the findings: which hold up, which are false positives
(and why), and which need a live source to settle.

**Why bother.** In one comparison on a dense technical document, a second Claude
model caught wrong facts, a GPT model caught broken reasoning, and the two lists
barely overlapped. Different model families miss different things.

## Install

```
/plugin marketplace add brackettmj/claude-skills
/plugin install peerreview@brackettmj-skills
export OPENROUTER_API_KEY=sk-or-...   # https://openrouter.ai/keys
```

Then ask: "get a peer review of report.md from another model."

## Cost and limits

- **Default model:** `openai/gpt-5.1`. A typical document costs $0.05–0.10. Change it
  with `--model` or `PEERREVIEW_MODEL`. `--list-models gemini` shows live prices.
- **Budget jar:** created on first use at `~/.config/peerreview/budget.json`, holding
  **$2.00 total, at most $0.50 per call**. Inside both limits a review runs without
  asking. Outside them it stops. Edit the file to change the limits.
- **Reserve, then settle:** the upper-bound cost is debited *before* the call and the
  difference refunded after, so a crash can only over-count. A call that dies mid-flight
  keeps its full reservation.
- **Content sweep:** before anything is sent, the prompt is checked for API keys,
  tokens, emails, phone numbers and account numbers. A hit stops the run.
- `--plan` shows the cost and any sweep hits and sends nothing. `--jar` and
  `--ledger` show spend so far.

## Use it without Claude

```
python3 skills/peerreview/scripts/peerreview.py report.md --plan
python3 skills/peerreview/scripts/peerreview.py report.md -o findings.md
python3 skills/peerreview/scripts/peerreview.py report.md --rubric my-rubric.md
```

Stdlib Python 3.9+, no install. Tests: `python3 -m unittest discover -s tests` (offline).

## What it's good at, and not

Good: contradictions, arithmetic, counts that don't match, invented names, claims
stated harder than the evidence. Not good: checking live facts (no web access) or
judging whether the writing is any good.
