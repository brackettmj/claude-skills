#!/usr/bin/env python3
"""Send a document to a non-Anthropic model for an independent review pass.

Claude Code can only spawn Claude subagents, so a same-family review shares most
of its blind spots with the author. This sends the document through OpenRouter
to a model from a different lab, which is where the independence comes from.

What a cross-model pass is good at: contradictions, unsupported leaps, invented
names, arithmetic, and claims stated harder than the evidence. What it is not
good at: checking live facts (a plain completion has no web access) and judging
whether the writing is any good.

    peerreview.py doc.md                       # default rubric
    peerreview.py doc.md --rubric review.md    # your own rubric
    peerreview.py doc.md --context notes.md    # reference material, not reviewed
    peerreview.py doc.md --plan                # cost and jar position, SENDS NOTHING
    peerreview.py doc.md -o findings.md
    peerreview.py --list-models gpt            # what's available today
    peerreview.py --jar                        # spent, remaining, per-call cap
    peerreview.py --ledger                     # every call so far, by model

Spending is capped by a local budget jar (default $2.00, at most $0.50 per call).
The jar is created on first use in the config directory; edit it to change the
limits. Inside both limits a review runs without asking. Outside them it stops,
and --approve lets one call through.

Needs OPENROUTER_API_KEY in the environment. Stdlib only, no install step.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://openrouter.ai/api/v1"
TIMEOUT = 300
DEFAULT_MODEL = "openai/gpt-5.1"
DEFAULT_JAR = 2.00
DEFAULT_CEILING = 0.50

# Characters per token. Rough on purpose: this feeds an upper-bound estimate,
# not a bill. Real usage comes back from the API and goes in the ledger.
CHARS_PER_TOKEN = 4


def config_dir() -> Path:
    """$PEERREVIEW_HOME, else $XDG_CONFIG_HOME/peerreview, else ~/.config/peerreview."""
    if os.environ.get("PEERREVIEW_HOME"):
        return Path(os.environ["PEERREVIEW_HOME"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base).expanduser() / "peerreview"


def budget_file() -> Path:
    return config_dir() / "budget.json"


def ledger_file() -> Path:
    return config_dir() / "ledger.jsonl"


def price_cache() -> Path:
    return config_dir() / "model-prices.json"


DEFAULT_RUBRIC = """\
Review the DOCUMENT below as an independent fact-checker. You did not write it.
Report defects only. Do not rewrite it, and do not produce a corrected version.

Check each of these:

1. Internal consistency. Contradictions between sections, counts that do not
   match the number of items that follow, cross-references pointing at the
   wrong place, claims undercut elsewhere in the document.
2. Arithmetic. Recompute every calculation shown. Verify each result follows
   from its stated inputs, and that the inputs themselves are plausible.
3. Names and entities. Flag any product, model, person, paper, or organization
   that you do not recognize or that looks fabricated. A plausible-sounding but
   non-existent name is the highest-value catch here.
4. Unsupported claims. Anything stated with more confidence than the evidence
   in the document supports, or presented as fact where it is really inference.
5. Logic. Conclusions that do not follow, analogies that break, causal claims
   resting on correlation.
6. Clarity. Passages that are genuinely hard to follow, and any place the
   document contradicts its own stated purpose or promises.

For each finding give: the location (quote a short phrase so it can be found),
the category, what is wrong, why you believe it is wrong, and a severity of
CRITICAL (a wrong fact a reader would act on), MAJOR (unsupported or
misleading), or MINOR (style or editorial).

Then list, separately, the specific claims you checked and believe are CORRECT,
so the value of this pass can be audited.

READ THE WHOLE DOCUMENT BEFORE YOU GRADE ANY OF IT. Many documents disclose
their own limits in a closing section: caveats, "things I could not confirm",
known gaps. Find that section first. Do not report as an undisclosed risk
anything the document already discloses; if the disclosure is present but too
weak or too far from the claim, say that instead, and say where it is.

You do not have web access, and this is the single biggest source of false
findings in this kind of review. Two rules follow.

First: DO NOT FILE UNVERIFIABLE CLAIMS AS INDIVIDUAL GRADED FINDINGS. Collect
them into one list at the end, headed UNVERIFIABLE HERE, with no severities
attached. Prices, release dates, benchmark scores, product specifications,
leaderboard positions and model names are almost always in this bucket. A
review where a third of the numbered findings are "I cannot check this" has
buried its real findings in restatement.

Second: your training data has a cutoff, and things exist that you have not
heard of. If you find yourself about to write that a product, paper, arXiv id,
or feature "may be hypothetical", "appears speculative", or "does not exist",
stop. That is a cutoff artifact, not a defect in the document. Put it in the
UNVERIFIABLE HERE list. Never assign it a severity, and never recommend
deleting or replacing a specific citation you merely fail to recognize.

What you SHOULD grade is everything checkable from the text alone: internal
contradictions, arithmetic, counts that do not match the items that follow,
claims undercut elsewhere in the same document, reasoning that does not follow,
and claims stated harder than the document's own evidence supports.

A review returning "looks good, minor suggestions" is a failed review. Dense
technical documents are rarely clean. Do not manufacture findings either: a
false accusation costs as much as a miss.
"""


class Refused(Exception):
    """A gate said no. The message says which gate and what to do about it."""


# --- OpenRouter -------------------------------------------------------------

def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("No OPENROUTER_API_KEY in the environment.\n"
                 "Get one at https://openrouter.ai/keys and export it:\n"
                 "    export OPENROUTER_API_KEY=sk-or-...")
    return key


def request(path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            # OpenRouter uses these for attribution; harmless and polite.
            "HTTP-Referer": "https://github.com/brackettmj/claude-skills",
            "X-Title": "peerreview",
        },
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:800]
        sys.exit(f"OpenRouter returned {exc.code}:\n{body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach OpenRouter: {exc.reason}")


def list_models(filter_text: str | None) -> None:
    rows = []
    for m in request("/models").get("data", []):
        mid = m.get("id", "")
        if filter_text and filter_text.lower() not in mid.lower():
            continue
        pricing = m.get("pricing", {})
        try:
            # OpenRouter quotes price per token; per-million is readable.
            prompt = float(pricing.get("prompt", 0)) * 1_000_000
            completion = float(pricing.get("completion", 0)) * 1_000_000
            price = f"${prompt:.2f} / ${completion:.2f}"
        except (TypeError, ValueError):
            price = "?"
        rows.append((mid, str(m.get("context_length", "?")), price))
    if not rows:
        print("No models matched.")
        return
    rows.sort()
    width = max(len(r[0]) for r in rows)
    print(f"{'MODEL'.ljust(width)}  {'CONTEXT'.rjust(9)}  IN/OUT per 1M")
    for mid, ctx, price in rows:
        print(f"{mid.ljust(width)}  {ctx.rjust(9)}  {price}")
    print(f"\n{len(rows)} model(s). Pass one with --model, or set PEERREVIEW_MODEL.")


def build_prompt(doc: str, doc_name: str, rubric: str,
                 contexts: list[tuple[str, str]]) -> str:
    parts = [rubric, ""]
    for name, body in contexts:
        parts += [
            f"--- REFERENCE MATERIAL: {name} ---",
            "This is context only. Do not review it; use it to judge the document.",
            body,
            f"--- END REFERENCE: {name} ---",
            "",
        ]
    parts += [f"--- DOCUMENT UNDER REVIEW: {doc_name} ---", doc, "--- END DOCUMENT ---"]
    return "\n".join(parts)


def review(model: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        # Low but not zero: findings should be stable, not creative.
        "temperature": 0.2,
    }
    result = request("/chat/completions", payload)
    choices = result.get("choices") or []
    if not choices:
        sys.exit(f"No response returned:\n{json.dumps(result, indent=2)[:800]}")
    return choices[0]["message"]["content"], result.get("usage", {})


# --- Cost -------------------------------------------------------------------

def model_prices(refresh: bool = True) -> dict:
    """{model_id: (prompt_per_token, completion_per_token)}, cached.

    /models is a free GET, but --plan should still price with no network, so a
    successful fetch is written to disk and a failed one falls back to the last
    one written.
    """
    prices = {}
    if refresh:
        try:
            listing = request("/models").get("data", [])
            # Anything but the expected shape falls through to the cache. An
            # odd pricing response should cost a stale estimate, never a
            # traceback in the middle of an approval.
            if not isinstance(listing, list):
                listing = []
            for m in listing:
                if not isinstance(m, dict):
                    continue
                pricing = m.get("pricing")
                if not isinstance(pricing, dict):
                    continue
                try:
                    prices[m["id"]] = (float(pricing.get("prompt", 0)),
                                       float(pricing.get("completion", 0)))
                except (TypeError, ValueError, KeyError):
                    continue
        except (SystemExit, AttributeError, TypeError):
            prices = {}
        if prices:
            try:
                price_cache().parent.mkdir(parents=True, exist_ok=True)
                price_cache().write_text(json.dumps(prices), encoding="utf-8")
            except OSError:
                pass
            return prices
    if price_cache().is_file():
        try:
            return {k: tuple(v) for k, v in
                    json.loads(price_cache().read_text(encoding="utf-8")).items()}
        except (json.JSONDecodeError, OSError, TypeError):
            return {}
    return {}


def balance() -> float | None:
    """Credits left on the key, or None if the endpoint can't be reached.

    On a key that has never been topped up, /credits reports total_credits 0,
    so this comes back negative. The verdict (can't afford it) is still right;
    the figure isn't a balance.
    """
    try:
        data = request("/credits").get("data", {})
        return float(data.get("total_credits", 0)) - float(data.get("total_usage", 0))
    except (SystemExit, TypeError, ValueError, AttributeError):
        return None


def estimate_cost(model: str, prompt: str, max_tokens: int,
                  prices: dict) -> tuple[float | None, int]:
    """(upper-bound dollars, estimated input tokens). None when price unknown.

    Output is priced at the full token cap, which almost never happens. That is
    on purpose: an estimate the real bill can beat is useless for approval.
    """
    in_tokens = max(1, len(prompt) // CHARS_PER_TOKEN)
    if model not in prices:
        return None, in_tokens
    prompt_rate, completion_rate = prices[model]
    return in_tokens * prompt_rate + max_tokens * completion_rate, in_tokens


def actual_cost(model: str, usage: dict, prices: dict) -> float | None:
    if model not in prices:
        return None
    prompt_rate, completion_rate = prices[model]
    return (usage.get("prompt_tokens", 0) * prompt_rate
            + usage.get("completion_tokens", 0) * completion_rate)


# --- Ledger -----------------------------------------------------------------

def append_ledger(entry: dict, path: Path | None = None) -> None:
    """One JSON line per real call. Append-only, and never fatal.

    A ledger write that could kill a run would be a reason to skip the ledger.
    """
    path = path or ledger_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"warning: could not write ledger at {path}: {exc}", file=sys.stderr)


def read_ledger(path: Path | None = None) -> list[dict]:
    path = path or ledger_file()
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue     # a torn line loses one row, not the whole history
    return rows


def summarize_ledger(rows: list[dict]) -> str:
    if not rows:
        return f"No calls recorded yet ({ledger_file()})."
    total = sum(r.get("cost") or 0 for r in rows)
    by_model: dict[str, list] = {}
    for r in rows:
        by_model.setdefault(r.get("model", "?"), []).append(r)
    width = max(len(m) for m in by_model)
    lines = [f"{len(rows)} call(s), ${total:.4f} total",
             f"first {rows[0].get('at', '?')}   last {rows[-1].get('at', '?')}", ""]
    for model, group in sorted(by_model.items()):
        spend = sum(r.get("cost") or 0 for r in group)
        lines.append(f"  {model.ljust(width)}  {len(group):>3} call(s)  ${spend:.4f}")
    unpriced = sum(1 for r in rows if r.get("cost") is None)
    if unpriced:
        lines.append(f"\n  {unpriced} call(s) had no price on file and count as $0 above.")
    return "\n".join(lines)


# --- Content sweep ----------------------------------------------------------
# Reads the ASSEMBLED PROMPT, which is the thing that actually leaves the
# machine. It will have false positives (a pricing document is full of numbers),
# which is what --approve is for, and why a hit names what it found and where
# instead of just refusing. A gate you can't argue with is one you learn to
# bypass without reading.

SWEEP_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI/OpenRouter key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone number", re.compile(r"\b(?:\+1[ -]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    # 13-19 unbroken digits is a card or account number. Prose numbers carry
    # separators ("327,680"), so this stays quiet on ordinary documents.
    ("account/card number", re.compile(r"(?<!\d)\d{13,19}(?!\d)")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("bank routing detail", re.compile(r"\brouting\s+number\b|\baccount\s+number\b",
                                       re.I)),
)


def sweep_prompt(prompt: str) -> list[tuple[str, str, int]]:
    """(label, the matched text, line number) for everything that looks sensitive."""
    hits = []
    for label, pattern in SWEEP_PATTERNS:
        for m in pattern.finditer(prompt):
            line = prompt.count("\n", 0, m.start()) + 1
            sample = m.group(0)
            if len(sample) > 40:
                sample = sample[:37] + "..."
            hits.append((label, sample, line))
    return hits


def format_sweep(hits: list[tuple[str, str, int]]) -> str:
    lines = [f"The pre-send sweep found {len(hits)} thing(s) in the assembled prompt:", ""]
    for label, sample, line in hits[:20]:
        lines.append(f"  line {line:>5}  {label:<22} {sample}")
    if len(hits) > 20:
        lines.append(f"  ... and {len(hits) - 20} more")
    lines += [
        "",
        "Nothing was sent. If these are benign (a pricing table, a public address",
        "in a quoted source), re-run with --approve. If you're not sure, it doesn't go.",
    ]
    return "\n".join(lines)


# --- Budget jar -------------------------------------------------------------
# Inside the jar, reviews run without asking, so this is the only thing between
# a mistake and the user's credits. It fails closed wherever it can: an
# unreadable jar, an uncostable call, or a failed reservation write all stop the
# run rather than send and hope. The one thing it does on its own is create a
# default jar on first use, because a missing jar is a fresh install, not damage.

def default_budget() -> dict:
    return {"jar": DEFAULT_JAR, "ceiling": DEFAULT_CEILING, "spent": 0.0,
            "since": datetime.datetime.now().isoformat(timespec="seconds")}


def ensure_budget(path: Path | None = None) -> bool:
    """Create the default jar if none exists. True when one was created."""
    path = path or budget_file()
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    write_budget(default_budget(), path)
    return True


def load_budget(path: Path | None = None) -> dict:
    """Read the jar, or refuse to run.

    The ledger tolerates a torn line because losing one row of history is cheap.
    The jar can't: an unreadable balance is an unknown balance, and spending
    against an unknown balance is what the jar exists to stop.
    """
    path = path or budget_file()
    if not path.is_file():
        raise Refused(f"No budget file at {path}.\n"
                      f"Create one with --init-budget.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused(f"Budget file at {path} is unreadable ({exc}).\n"
                      f"Refusing to spend against a balance it can't read.")
    if not isinstance(data, dict):
        raise Refused(f"Budget file at {path} is not a JSON object.")
    out = {}
    for key in ("jar", "ceiling", "spent"):
        val = data.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
            raise Refused(f"Budget file at {path} has a bad '{key}' ({val!r}).\n"
                          f"Refusing to spend against a jar it can't read.")
        out[key] = float(val)
    # Optional, and only used to scope the ledger cross-check. A jar opened
    # today shouldn't be blamed for spend that predates it.
    since = data.get("since")
    if since is not None and not isinstance(since, str):
        raise Refused(f"Budget file at {path} has a bad 'since' ({since!r}).")
    if since is not None:
        out["since"] = since
    return out


def budget_left(budget: dict) -> float:
    return budget["jar"] - budget["spent"]


def write_budget(budget: dict, path: Path | None = None) -> None:
    """Atomic. A crash mid-write leaves the old jar, never half a jar."""
    path = path or budget_file()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def check_budget(cost: float | None, budget: dict) -> None:
    """Raise unless this call is inside both limits. Unknown cost never passes."""
    if cost is None:
        raise Refused("No price on file for this model, so the call can't be costed.\n"
                      "Check the id with --list-models, or approve this one call "
                      "with --approve.")
    if cost > budget["ceiling"]:
        raise Refused(f"Over the per-call ceiling: ${cost:.4f} at the output cap, "
                      f"ceiling ${budget['ceiling']:.2f}.\n"
                      f"Lower --max-tokens, pick a cheaper model, or approve this "
                      f"call with --approve.")
    left = budget_left(budget)
    if cost > left:
        raise Refused(f"Not enough left in the jar: ${cost:.4f} at the output cap, "
                      f"${left:.4f} remaining of ${budget['jar']:.2f}.\n"
                      f"Raise 'jar' in {budget_file()}, or approve this call "
                      f"with --approve.")


def reserve_budget(cost: float, budget: dict,
                   path: Path | None = None) -> tuple[dict, float]:
    """Debit the upper bound BEFORE the call; return (jar, amount reserved).

    settle_budget() must be given the returned, rounded amount. Reserving a
    rounded number and refunding an unrounded one leaves a sub-cent residue in
    the jar on every call.

    Order is the point. Debiting afterwards means a crash mid-call spends money
    the jar never hears about. Reserving first can only over-count, and
    settle_budget() hands the difference back. A call that dies before settling
    keeps its full reservation: the jar errs toward spending less.
    """
    cost = round(cost, 6)
    updated = dict(budget)
    updated["spent"] = round(budget["spent"] + cost, 6)
    try:
        write_budget(updated, path)
    except OSError as exc:
        raise Refused(f"Could not record the reservation in the budget file ({exc}).\n"
                      f"Refusing to send: an unrecorded spend is how the jar drifts.")
    return updated, cost


def settle_budget(reserved: float, actual: float | None, budget: dict,
                  path: Path | None = None) -> dict:
    """Give back the gap between the output cap and what was actually used."""
    if actual is None:
        return budget          # unpriced result: keep the conservative figure
    updated = dict(budget)
    updated["spent"] = round(budget["spent"] - reserved + round(actual, 6), 6)
    try:
        write_budget(updated, path)
    except OSError as exc:
        print(f"warning: could not settle the budget ({exc}); the jar still "
              f"shows ${reserved:.4f} for this call rather than ${actual:.4f}.",
              file=sys.stderr)
        return budget
    return updated


def format_budget(budget: dict, rows: list[dict] | None = None,
                  path: Path | None = None) -> str:
    lines = [
        f"BUDGET JAR: {path or budget_file()}",
        "",
        f"  jar            ${budget['jar']:.2f}",
        f"  spent          ${budget['spent']:.4f}",
        f"  remaining      ${budget_left(budget):.4f}",
        f"  per-call cap   ${budget['ceiling']:.2f}",
    ]
    if rows is not None:
        since = budget.get("since")
        if since:
            rows = [r for r in rows if (r.get("at") or "") >= since]
        ledger_total = sum(r.get("cost") or 0 for r in rows)
        lines += ["", f"  ledger says    ${ledger_total:.4f} across {len(rows)} call(s)"
                      + (f" since {since}" if since else "")]
        # Both are written from the same actual-cost number, so a gap means a
        # settle failed or the jar was hand-edited. Worth seeing, not fatal.
        if abs(ledger_total - budget["spent"]) > 0.0005:
            lines.append("  ** jar and ledger disagree: one was edited or a settle failed **")
    return "\n".join(lines)


# --- The review run ---------------------------------------------------------

def run_review(args) -> int:
    doc_path = Path(args.document).expanduser()
    if not doc_path.is_file():
        raise Refused(f"Not a file: {doc_path}")

    model = args.model or os.environ.get("PEERREVIEW_MODEL", "").strip() or DEFAULT_MODEL

    rubric = DEFAULT_RUBRIC
    if args.rubric:
        rubric_path = Path(args.rubric).expanduser()
        if not rubric_path.is_file():
            raise Refused(f"Not a file: {rubric_path}")
        rubric = rubric_path.read_text(encoding="utf-8")

    contexts = []
    for item in args.context:
        p = Path(item).expanduser()
        if not p.is_file():
            raise Refused(f"Not a file: {p}")
        contexts.append((p.name, p.read_text(encoding="utf-8")))

    # Without a key the price fetch fails quietly and the plan reads "no price
    # on file", which sends people hunting for a bad model id. Say the real
    # problem. --offline prices from the cache, so it can run without one.
    if not args.offline and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise Refused("No OPENROUTER_API_KEY in the environment, so prices can't be "
                      "fetched and nothing can be sent.\n"
                      "Get one at https://openrouter.ai/keys and export it:\n"
                      "    export OPENROUTER_API_KEY=sk-or-...")

    doc = doc_path.read_text(encoding="utf-8")
    prompt = build_prompt(doc, doc_path.name, rubric, contexts)

    budget_path = Path(args.budget_file).expanduser() if args.budget_file else None
    if ensure_budget(budget_path):
        print(f"Created a budget jar at {budget_path or budget_file()}: "
              f"${DEFAULT_JAR:.2f} total, ${DEFAULT_CEILING:.2f} per call. "
              f"Edit it to change the limits.", file=sys.stderr)
    budget = load_budget(budget_path)
    prices = model_prices(refresh=not args.offline)
    cost, in_tokens = estimate_cost(model, prompt, args.max_tokens, prices)
    hits = sweep_prompt(prompt)

    if args.plan:
        lines = [
            "REVIEW PLAN: nothing has been sent.",
            "",
            f"  document       {doc_path.name} ({len(doc):,} chars)",
            f"  model          {model}",
            f"  input          ~{in_tokens:,} tokens",
            f"  output cap     {args.max_tokens:,} tokens",
            "  est. cost      " + ("unknown, no price on file for this model"
                                   if cost is None else
                                   f"${cost:.4f}  (upper bound: output priced at the cap)"),
            f"  jar            ${budget_left(budget):.4f} left of ${budget['jar']:.2f}",
            f"  per-call cap   ${budget['ceiling']:.2f}",
        ]
        if not args.offline:
            left = balance()
            if left is not None:
                lines.append(f"  credits left   ${left:.4f}")
                if cost is not None and left < cost:
                    lines.append("  ** OpenRouter will reject this: the account can't "
                                 "cover the output cap. **")
        if hits:
            lines.append(f"  ** CONTENT SWEEP: {len(hits)} hit(s). This stops "
                         f"unless you pass --approve. **")
            for label, sample, line_no in hits[:5]:
                lines.append(f"       line {line_no}: {label}: {sample}")
        try:
            check_budget(cost, budget)
        except Refused as exc:
            lines.append(f"  ** WILL STOP: {str(exc).splitlines()[0]} **")
        print("\n".join(lines))
        return 0

    if args.approve:
        print("--approve: bypassing the jar, the per-call ceiling and the content "
              f"sweep ({len(hits)} hit(s)) for this one call. It is still recorded.",
              file=sys.stderr)
    else:
        if hits:
            raise Refused(format_sweep(hits))
        check_budget(cost, budget)
    reserved = 0.0
    if cost is not None:
        budget, reserved = reserve_budget(cost, budget, budget_path)

    print(f"Reviewing {doc_path.name} ({len(doc):,} chars) with {model}...",
          file=sys.stderr)
    findings, usage = review(model, prompt, args.max_tokens)

    actual = actual_cost(model, usage, prices)
    append_ledger({
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
        "document": doc_path.name,
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost": round(actual, 6) if actual is not None else None,
    })
    if reserved:
        budget = settle_budget(reserved, actual, budget, budget_path)
    print(f"{f'${actual:.4f} · ' if actual is not None else ''}"
          f"jar ${budget_left(budget):.4f} of ${budget['jar']:.2f} left",
          file=sys.stderr)

    header = (
        f"# Peer review: {doc_path.name}\n\n"
        f"**Reviewer model:** {model}\n"
        f"**Tokens:** {usage.get('prompt_tokens', '?')} in / "
        f"{usage.get('completion_tokens', '?')} out\n\n"
        f"> No web access. Anything under UNVERIFIABLE HERE still needs checking.\n\n---\n\n"
    )
    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(header + findings + "\n", encoding="utf-8")
        print(f"Wrote {out}", file=sys.stderr)
    else:
        print(header + findings)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Independent review of a document by a non-Anthropic model.",
        epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("document", nargs="?", help="File to review")
    ap.add_argument("--model", help=f"OpenRouter model id (default: $PEERREVIEW_MODEL, "
                                    f"else {DEFAULT_MODEL})")
    ap.add_argument("--rubric", help="File holding review instructions (default: built in)")
    ap.add_argument("--context", action="append", default=[], metavar="FILE",
                    help="Reference material the reviewer reads but doesn't review. Repeatable.")
    ap.add_argument("-o", "--output", help="Write the result here instead of stdout")
    ap.add_argument("--max-tokens", type=int, default=8000, help="Response cap (default 8000)")
    ap.add_argument("--plan", action="store_true",
                    help="Show the cost, the jar and any sweep hits, and SEND NOTHING")
    ap.add_argument("--approve", action="store_true",
                    help="Let one call past the jar, the per-call ceiling and the sweep")
    ap.add_argument("--offline", action="store_true",
                    help="Price from the cached model list instead of fetching it")
    ap.add_argument("--list-models", nargs="?", const="", metavar="FILTER",
                    help="List available models and exit. Optional substring filter.")
    ap.add_argument("--jar", action="store_true", help="Show the budget jar and exit")
    ap.add_argument("--ledger", action="store_true", help="Summarize spend so far and exit")
    ap.add_argument("--init-budget", action="store_true",
                    help=f"Create the budget jar (${DEFAULT_JAR:.2f}, "
                         f"${DEFAULT_CEILING:.2f} per call) and exit")
    ap.add_argument("--budget-file", metavar="FILE",
                    help="Budget jar to draw from (default: in the config directory)")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    budget_path = Path(args.budget_file).expanduser() if args.budget_file else None
    try:
        if args.ledger:
            print(summarize_ledger(read_ledger()))
            return 0
        if args.init_budget:
            path = budget_path or budget_file()
            if not ensure_budget(budget_path):
                raise Refused(f"{path} already exists. Edit it rather than "
                              f"overwrite a jar that may have spend in it.")
            print(f"Created {path}: ${DEFAULT_JAR:.2f} jar, "
                  f"${DEFAULT_CEILING:.2f} per-call cap.")
            return 0
        if args.jar:
            print(format_budget(load_budget(budget_path), read_ledger(), budget_path))
            return 0
        if args.list_models is not None:
            list_models(args.list_models or None)
            return 0
        if not args.document:
            ap.error("a document is required (or use --list-models, --jar, --ledger)")
        return run_review(args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
