# Before and after

A fictional weekly status update, run through both modes.

## The original

> In today's fast-paced digital landscape, ensuring robust platform reliability is more
> important than ever. This week, the team continued to leverage our cutting-edge
> monitoring stack to streamline incident response and elevate the customer experience.
>
> It's worth noting that we saw a significant improvement in resolution times, which
> could potentially unlock further efficiencies moving forward. Additionally, we
> facilitated several cross-functional syncs to drive alignment. Moreover, the
> migration remains on track.
>
> In conclusion, it was a productive week, and we're excited to keep the momentum going!

## Review mode

| # | Quote | Category | Fix |
|---|---|---|---|
| 1 | "In today's fast-paced digital landscape… more important than ever" | Filler: empty opener | Delete the sentence. Start with what happened this week. |
| 2 | "significant improvement in resolution times" | Not concrete | Give the numbers: median time to resolve, from what to what. |
| 3 | "leverage our cutting-edge monitoring stack to streamline… and elevate" | Overused words (4 in one sentence) | Say what the monitoring did: "new alerts paged us before customers noticed, twice." |
| 4 | "It's worth noting that… could potentially unlock" | Hedge + overused word | Commit or cut: "If this holds, we can drop the second on-call." |
| 5 | "In conclusion, it was a productive week… keep the momentum going!" | Wrap-up + unearned exclamation | Delete. The update already ended. |
| 6 | "Additionally… Moreover…" | Hollow transitions | Delete both words. The sentences stand on their own. |
| 7 | "facilitated several cross-functional syncs to drive alignment" | Overused word, no content | What was decided? If nothing, cut the line. |
| 8 | "the migration remains on track" | Not concrete | On track for what date, and what's left? |

**Habits to watch:** opening with a scene-setter instead of the news, and describing
effort ("leverage", "facilitated", "drive alignment") instead of results.

## Draft mode

The review asked for numbers the original never gave, so draft mode asks before
writing: *What did resolution time go from and to? What did the alerts actually do?
How many services are migrated, and what's the date?* The writer answered all but
one. Every fact below came from those answers.

> Median time to resolve dropped from 4h 10m to 1h 35m this week. Most of the gain came
> from the new database alerts, which paged us before customers noticed in two of three
> incidents.
>
> If that holds for two more weeks, we can drop the secondary on-call rotation.
> [owner] is drafting the proposal.
>
> Migration: 14 of 22 services moved. The remaining 8 are on schedule for Nov 15. The
> one risk is the billing service, which needs a schema change first.

About the same length (81 words to 84). The original made three vague claims; this
makes ten specific ones. Plain writing isn't always shorter. It spends the words on
things the reader can use.

The bracketed gap is the one question the writer couldn't answer (who owns the
proposal), so the draft marks it instead of guessing.
