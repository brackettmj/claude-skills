# Checkout returned 503s for 41 minutes after a cache config change

_Fictional incident at a fictional online bookstore, written with the `postmortem` skill
to show the output. Every name, time and number is made up._

**Summary.** From 14:07 to 14:48 UTC, 38% of checkout requests failed with 503s.
Because each order retries checkout up to three times, 22% of orders failed outright.
A config change set the price-cache TTL to 0, which sent every price lookup to the
catalog database and exhausted its connection pool. Rolling back the change restored
service, and the pool has held under 40% through two daily peaks since.

## 1. Clock

| Event | Time (UTC) | Source |
|---|---|---|
| Config change merged and deployed | 14:05 | deploy log |
| First failure | 14:07 | load balancer 5xx log |
| Detected, by the checkout error-rate alert | 14:11 | paging tool |
| Correct diagnosis (cache TTL = 0) | 14:39 | incident channel |
| Mitigation deployed (config rollback) | 14:46 | deploy log |
| Fix verified (5xx back to baseline for 10 min) | 14:58 | dashboard |

| Interval | Value |
|---|---|
| End to end (deploy → verified) | 53 min |
| Time to detect (first failure → page) | 4 min |
| Time to correct diagnosis (page → TTL found) | 28 min |
| Time to mitigate (TTL found → rollback live) | 7 min |

## 2. Impact

- **Baseline:** checkout was healthy before 14:05. This was an outage, not a failed launch.
- **By unit:**

| Unit | Attempted | Failed | Rate |
|---|---|---|---|
| Checkout requests | ~31,000 | ~11,800 | 38% |
| Orders (up to 3 attempts each) | 9,410 | 2,070 | 22% |
| Customers who abandoned after failing | — | 1,390 | — |

- **Blast radius:** search and browse also slowed (p95 latency 4× normal), since they
  share the catalog database. No other service failed.

## 3. Who was involved

| Who | Role | Record |
|---|---|---|
| On-call engineer, checkout | Incident commander | incident channel, paging log |
| On-call engineer, catalog | Database diagnosis | incident channel |
| Config change author | Joined at 14:31 | incident channel, PR |
| Support lead | Customer comms | support ticket queue |

## 4. Timeline

| Time | Event | Evidence that drove the next decision |
|---|---|---|
| 14:05 | Price-cache TTL change deployed as part of a batch of 6 config edits | — |
| 14:11 | Checkout error-rate alert pages checkout on-call | 503 rate at 31% |
| 14:14 | IC suspects the 14:02 checkout code deploy and starts a rollback | It was the most recent *code* deploy on the dashboard |
| 14:26 | Code rollback complete; errors unchanged | Rules out the code deploy |
| 14:29 | Catalog on-call reports DB connection pool at 100% | DB dashboard |
| 14:31 | Config author joins after seeing the channel | — |
| 14:39 | Cache hit rate found at 0% since 14:05; TTL change identified | Cache dashboard |
| 14:46 | Config batch rolled back | Deploy log |
| 14:58 | 5xx at baseline for 10 min, pool at 35% | Dashboards |

## 5. Root cause: the whys

**Chain A — why did checkout fail?**
1. Checkout timed out waiting on price lookups. → Why?
2. The catalog DB connection pool was exhausted. → Why?
3. Every price lookup missed the cache and hit the DB. → Why?
4. The cache TTL was set to 0, which the cache client treats as "don't cache." → Why
   was 0 allowed?
5. **Bottom (owned):** the config schema accepts any integer for TTL. A value of 0
   was meant as "use the default," which is what it means in a different service's
   config.

**Chain B — how did it get shipped?**
1. The change rode in a batch of six config edits with one reviewer. → Why?
2. **Bottom (owned):** config changes don't need the owning team's review. The
   catalog team never saw this one.

**Chain C — why didn't testing catch it?**
1. Staging passed. → Why?
2. Staging traffic is about 1% of production, and the DB pool never saturated.
3. **Bottom (owned):** no pre-deploy check compares cache hit rate before and after.

**Chain D — why did diagnosis take 28 minutes?**
1. The IC rolled back the code deploy first. → Why?
2. The deploy dashboard shows code deploys but not config deploys.
3. **Bottom (owned):** config changes have no "recent changes" view next to code.

**Chain E — why did it spread to search?**
1. Search shares the catalog DB pool. **Unknown whether a separate pool would have
   held, stopped because** we have no load test at this traffic level. See action 6.

## 6. Controls still in place

| Control | Status |
|---|---|
| Config batch rolled back | Proven to matter: errors stopped within 2 min |
| Code deploy rolled back at 14:26 | Proven useless for this incident. Redeployed 15:30 |
| DB pool raised from 200 to 300 during the incident | Unproven: still in place. Test or revert, action 7 |

## 7. Counter-evidence

- Error rate peaked at 14:20 and dipped slightly before the rollback. Not explained.
  One guess is clients backing off, unverified.
- We don't have per-customer retry data, so the 1,390 abandoned-checkout count comes
  from session ends within 5 minutes of a failure and is an estimate.

## 8. What went well, what didn't

- **Went well:** the alert paged within 4 minutes. Support posted a status banner by 14:20.
- **Didn't:** 12 minutes spent rolling back the wrong change, because config deploys
  are invisible on the dashboard (Chain D).
- **Went well, still a gap:** the config author saw the channel and joined on their
  own. That was luck, not process.

## 9. Action items

| # | Item | Chain | Type | Owner | Tracking |
|---|---|---|---|---|---|
| 1 | Reject TTL = 0 in the config schema; require an explicit "default" | A | prevent | Catalog eng lead | CAT-412 |
| 2 | Require owning-team review on config that touches another team's service | B | prevent | Platform eng lead | PLAT-88 |
| 3 | Pre-deploy check: block if cache hit rate drops >20 points in canary | C | detect | Catalog eng lead | CAT-413 |
| 4 | Show config deploys on the recent-changes dashboard | D | detect | Observability lead | OBS-51 |
| 5 | Page the author of any change deployed in the 30 min before an incident | D | mitigate | Incident mgmt lead | INC-19 |
| 6 | Load-test search on a separate DB pool | E | verify | Search eng lead | SRCH-207 |
| 7 | Keep or revert the pool increase after the load test | — | verify | Catalog eng lead | CAT-414 |

**Exec version**
- **Impact:** 22% of orders failed for 41 minutes (2,070 orders).
- **Cause:** a config change disabled the price cache and overloaded the catalog database.
- **Fix:** rolled back. Stable through two peaks since.
- **Key action:** the config schema will reject the value that caused this (CAT-412).
