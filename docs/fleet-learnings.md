# Fleet learnings — what the sites have taught us

**Started:** 2026-11-21
**Source:** each site's `sites/<domain>/docs/growth.md` (reviewed Result /
Learning fields), plus fleet-wide probes and `lamill project seo --deep` runs.
**Use:** read before planning a new site, a new content batch, or an
indexing fix. Each lesson names the sites and entries it comes from, so it
can be re-checked; a lesson with one source is a lead, not a rule.

This is a working doc, not one of the five canonical surfaces. Per-site
detail stays in that site's `growth.md`; this file is the cross-site roll-up.

## When to update

- **Whenever we learn something new** — a site's `growth.md` review fills in
  a Result / Learning, a `lamill project seo --deep` run finds a cause, or a
  fleet-wide probe shows a pattern.
- **Full review at least every 6 months** — re-check each lesson against the
  latest results, mark what still holds, and edit what doesn't (dated).
  Last reviewed: 2026-11-21 (started). Next review due: **2027-05-21**.

## How to add a lesson

- Add it under the right section as a bullet: **the lesson in bold**, then
  the evidence (site, date, numbers) and where it was recorded.
- Only reviewed outcomes count — a `Result:` that's been filled in, a live
  probe, or a `--deep` report. Hypotheses go under *Open questions*.
- When a later result contradicts a lesson, edit the lesson and say so with
  the date; don't silently delete it.

---

## Choosing a domain

- **Never use `.xyz` (operator rule, 2026-11-21: "xyz has been 0 - 0 - 0,
  never go with xyz TLD").** Fleet `fleet seo` snapshot 2026-11-22, 28-day
  GSC: meetwhen.xyz 1 impression / 0 clicks (1/10 inspected URLs indexed),
  threadradar.xyz 0 / 0. The other `.xyz` domains (donready, earnlog,
  scopeguard, mathbloom, dailyring, permittruck) aren't in that snapshot's
  scope. Caveat: small sample and mostly one-page sites, so TLD isn't
  isolated from site size — but the operator's call stands regardless.
- **The same snapshot shows `.com` doing best and some other TLDs near
  zero** — a lead, not a rule, since TLD is confounded with site age,
  content depth and niche. `.com` 25 sites, 28d impressions median 93 (top:
  montereybayevents 21,962, hybridautopart 17,982, whizgraphs 7,041,
  cottagefoodmap 5,743). `.dev` 4 sites, 1 impression total. `.site` 3 sites,
  93 total, all three stuck at homepage-only indexing. `.app` 4 sites, 2,002
  total but 2,000 of it is washcalc.app. Single-site TLDs (`.pics` 1,587,
  `.today` 121, `.store` 45, `.io` 42) can't be judged.
- **An exact-match domain added almost nothing to traffic.**
  montereybayevents.com, ~110 days of GSC to 2026-11-18: queries containing
  "monterey bay events" = 57 impressions (0.2%) and 2 clicks (0.4%), ranking
  ~pos 23; every "monterey bay" query together = 0.6%. The traffic came from
  specific event / festival / month / map queries that don't contain the
  domain words. Caveat: query data can't show any click-through or trust
  effect of a descriptive name, and GSC withholds rare queries (~80% of this
  site's impressions aren't attributed to a query). Pick a domain for
  memorability and fit, not for its keywords.

## Getting pages crawled

- **A sitemap gets a site found, not its pages crawled.** Resubmitting a
  sitemap got it downloaded but moved no URLs on low-authority domains.
  markpdf.dev: sitemap fetched 2026-07-25, 6 of 7 URLs still "unknown to
  Google" 10 weeks later (`growth.md`, reviewed 2026-10-02). marginready.com:
  sitemap fetched once, then not again for 6 weeks. calcengine.site: sitemap
  complete (81 URLs) and downloaded 2026-11-15, 80 URLs still unknown
  (`--deep` 2026-11-16).
- **Clear crawl blockers before starting any experiment clock.** These cost
  whole review windows:
  - client-rendered empty pages — kwizicle.com ("deploy + sitemap alone
    produced nothing because prod HTML was a blank CSR shell");
  - canonical / sitemap / served URL disagreeing, incl. trailing slashes —
    whizgraphs.com (first 28d window spent on crawl blockers; first
    impression only after the fixes), markpdf.dev (links without the 308
    hop coincided with URLs moving to "discovered", 2026-10-30);
  - soft-404 catch-alls — see the next bullet.
- **Unknown paths must return 404, not 200 (soft-404 catch-all).** Probe
  2026-11-21 (`/zz-no-such-page-8731`, Googlebot UA): 5 of the 8 sites stuck
  at "homepage indexed, inner pages unknown" returned **200** — homeloom.app,
  keralavotemap.site, kwizicle.com, meetwhen.xyz, voltloop.site. Every
  well-indexed site probed returned 404 (cottagefoodmap.com, lamill.store,
  dearreels.com, retouchlint.com). boxchive.com went from homepage-only to
  8/10 inspected URLs indexed within days of a deploy whose fixes included
  the soft-404 (v2.B, `growth.md` 2026-10-30 entry, interim 2026-11-19) —
  but that deploy also added pages and canonicals, so the soft-404's share
  isn't isolated. calcengine.site returns 404, so this isn't its cause.
  *Lead, not proven — weakened 2026-11-25:* a full fleet probe found **16** live
  sites returning 200, including iotbastion.com (9/10 indexed) and dunam.co
  (7/7 indexed), so soft-404 alone doesn't stop indexing. Root cause is
  lamill's `new bootstrap` writing `not_found_handling:
  "single-page-application"` for Astro sites — fix tracked as PRD v46.G–I.
- **Weeks of "discovered / unknown" despite internal links usually means
  low crawl priority, not missing links.** marginready.com: `/tools/` linked
  from every footer and body content for ~8 weeks, still unknown.
  calcengine.site: `/calculators` has 80 inbound links and sits one click
  from a crawled homepage, still unknown. kwizicle.com: "discovered – not
  indexed" for 15 weeks with links in place. Adding more internal links
  hasn't been shown to fix this.
- **Google can crawl pages and later drop them entirely.** calcengine.site:
  calculator pages appear as referrers of the homepage (so they were
  fetched) yet every URL variant now inspects as "unknown" (2026-11-16).

## What to build

- **Subjects that keep producing pages have the most SEO room; narrow
  product-name sites have a low ceiling.** GSC 90d to 2026-11-20: the
  sites with breadth (events × towns × months, states × foods, parts) lead —
  montereybayevents 61,695 impressions / 2,291 queries, cottagefoodmap
  10,438 / 462 (+95% vs the prior 28d), hybridautopart 63,781 / 2,187. The
  single-product B2B sites (dropaudit, pqhorizon, mdburst, iotbastion, …)
  sit at 2–68 queries each. Two signals of untapped room: **many queries per
  page** (isitholiday.today: 328 queries reaching only 4 pages) and **a big
  pool at positions 5–20** (hybridautopart: 17,773 impressions). For a
  narrow product, the SEO angle is the regulation or problem it solves, not
  the product name.
- **Reference win: montereybayevents.com** (launched 2026-08; GSC pulled
  2026-11-21). Impressions and clicks every week since launch, ~4,000–6,500
  impressions and 65–240 clicks a week; 328 clicks in the 28 days to the
  2026-11-22 snapshot, the fleet's highest; 10/10 inspected URLs indexed;
  3,312 image-search impressions on top (28d). None of its `growth.md`
  entries has a reviewed Result yet, so the lessons below are read from GSC
  against what each entry bet on — per-bet credit is unconfirmed. What it
  did:
  - **One page per intent, not one filter per intent.** Individual event
    pages and month hubs carry the clicks: Watsonville Día de Muertos 55
    clicks / pos 6.8, Castroville Artichoke Festival 38 / pos 5.3,
    `/events/november/` 50 / pos 5.1, `/events/december/` 18 (28d).
  - **Dated, specific queries convert; head terms don't.** "castroville
    artichoke festival 2026" pos 1.7, "monterey events november 2026" pos 2.4,
    "artichoke festival california" pos 3.5. Year-stamped pages rank ahead:
    "monterey car week 2027" already 1,206 impressions.
  - **Year-round beats seasonal.** Began as a Car Week page; widened on
    2026-08-03 into a two-county year-round calendar (61 events) and later
    farmers markets; traffic held at 5,000+ impressions a week through
    October–November, after Car Week.
  - **Verified facts beat the incumbents.** Every "free" listing checked
    against its organiser (two non-free removed, two wrong venues fixed,
    2026-08-12); market times checked against operators where competing pages
    were stale; anything unconfirmed visibly marked `[VERIFY]` instead of
    guessed.
  - **Structured data on every page:** `Event` JSON-LD (dates, offers,
    organiser, address), `FAQPage`, `ItemList`.
  - **Queries chosen from keyword data, aimed at gaps:** KD-0 / low-KD terms
    ("laguna seca map"), real recurring demand ("monterey farmers market",
    ~500/mo), unanswered local queries ("monterey bay card show"), and
    logistics intent the incumbents' map apps don't serve as indexable HTML.
  - **Clean from day one:** `new bootstrap`, server-rendered, complete
    sitemap, GSC at deploy, real 404s — indexed immediately.
  - It's the pilot for the planned v54 `micros` category (was v47), so these patterns
    are meant to be copied.
- **Check search volume before building pages.** calcengine.site v1: 58
  developer calculators at ~0–30 US searches/month; even indexed they could
  not have earned impressions, and they may have lowered crawl priority
  site-wide (`growth.md` 2026-10-31). boxchive.com: "digitization for [org
  type]" pages measured ~0 in SE Ranking; task queries (cost, scanning) are
  where demand is.
- **Fewer substantive pages beat many thin ones.** lamillrentals.com:
  cutting to 18 substantive URLs took indexing from 0 to 14 of 18.
  airsucks.com: a long-parked domain re-indexed 7/8 URLs once routes served
  real prerendered HTML and a complete sitemap.
- **Narrow task and question queries earn the impressions and clicks; head
  terms and hubs don't.** cottagefoodmap.com: "can I sell" guides carried
  1,678 of 2,558 impressions and 26 of 28 clicks (28d to 2026-10-18); state
  pages 666 imp / 3 clicks. lamill.pics: long-tail Christian / Malayalam
  good-morning queries, not head terms. boxchive.com: the cost page leads
  non-home impressions.
- **Prove a page template, then roll it out in batches.** cottagefoodmap.com:
  batch 1 — 50/50 new URLs indexed, 507 imp; batch 2 — 49/50 indexed, 994 imp
  / 17 clicks / pos 9.1, beating batch 1 in its first window.
- **Per-item pages and original images pull image search.** lamill.pics:
  per-picture pages got into Google Images within 4 weeks; 5,754 image
  impressions vs 1,238 web (28d to 2026-11-03). montereybayevents.com:
  original maps / printable calendar — `/laguna-seca-map/` 1,952 web
  impressions at pos 6.6, plus 3,312 image-search impressions site-wide (28d
  to 2026-11-18).
- **Image search is a cheap impressions lever — use it while impressions
  are the funnel stage we're optimizing (operator, 2026-11-21).** Fleet, 28d
  to 2026-11-18: image search 18,245 impressions on top of web's 61,908
  (+~30%), from essentially three sites — hybridautopart.com 7,326,
  lamill.pics 7,265, montereybayevents.com 3,312. It converts far worse:
  59 clicks (~3 per 1,000 impressions) vs web's 569 (~9 per 1,000), and
  hybridautopart alone has 46 of the 59 (part photos — the image *is* the
  answer). So: add original, per-item images wherever a query is visual;
  count them as an impressions win; don't expect clicks until they rank
  (lamill.pics sits ~pos 45 in image results) or the image is what the
  searcher wants.

## After indexing: ranking

- **Once indexed, ranking is the limit — positions ~8–70 bring impressions,
  not clicks.** lamillrentals.com ("indexing is no longer the constraint;
  ranking is"), retouchlint.com (55 imp / 0 clicks / pos 29.9),
  mspproof.com (121 imp / 0 clicks / pos 68.3), cottagefoodmap.com state
  pages, lamill.pics images (~pos 45). Even on the fleet's best site the
  broad hub lags: montereybayevents.com `/monterey-car-week/` 3,768
  impressions / 19 clicks at pos 11.1 (28d), while its specific event pages
  rank 5–7 and get the clicks.
- **Watch for cannibalization once a cluster grows.** boxchive.com:
  "historical document scanning" split between the `/guides/` hub and the
  pillar (2026-11-19).

## Measuring

- **Read per-URL coverage before judging any result.** "Unknown to Google"
  and "indexed but ranks badly" both show 0 impressions and need opposite
  fixes (marginready.com). `lamill project seo <domain> --deep` gives the
  per-URL picture.
- **Connect GSC before launch, and check indexing within 2 weeks of the
  first deploy.** mdburst.com measured nothing for months (property never
  verified). calcengine.site shipped 58 pages in 2026-04 and indexing wasn't
  measured until 2026-10-05.
- **Change one thing per review window.** cottagefoodmap.com: a title change
  shipped alongside new content, so the CTR gain couldn't be credited.
  boxchive.com: soft-404 fix + new pages in one deploy.
- **Reviews run late.** Most reviewed entries were days to weeks past their
  date (marginready.com 36 days, airsucks.com ~3 months). A late review still
  beats none, but note the actual window used. montereybayevents.com — the
  fleet's best performer — has no reviewed entry at all as of 2026-11-21, so
  even its wins aren't credited bet by bet.
- **`project seo` counts web search only.** lamill.pics' image impressions
  (4.6× web) are invisible to it.

## Opportunity map — where SEO effort should go

*Assessment, 2026-11-23 — not reviewed outcomes. Built from GSC (90d to
2026-11-20: impressions, query spread, positions 5–20, last 28d vs the
prior 28d) plus each site's subject from its `AI_AGENTS.md`. Demand was
**not** sized with keyword data (Ahrefs / treg cost per lookup), so treat
the rankings as judgement. Re-run at the 6-month review.*

- **Tier 1 — broad subject, proven, invest most:** montereybayevents.com
  (61,695 imp / 1,219 clicks; new events, towns, months, next year),
  hybridautopart.com (63,781 imp; 17,773 at positions 5–20 on 52 pages —
  move rankings, not more pages), cottagefoodmap.com (10,438 imp, +95%; 20 of
  50 states covered), isitholiday.today (850 imp but 328 queries on 4 pages
  — every holiday × country × year unbuilt).
- **Tier 2 — broad demand, stuck on ranking or depth:** whizgraphs.com
  (18,837 imp, 0 clicks — competitive head terms; image search v2.F),
  lamill.pics (image-led, low value per visitor), airsucks.com (HVAC
  problems; thin pages), washcalc.app (steady +37%), boxchive.com (+482%,
  just moving).
- **No traction yet, but worth a retarget** (ranked):
  1. thoralox.com — demand is on **named and vendor-level** vulnerabilities,
     not raw CVE IDs (corrected 2026-11-23 with keyword data; the first
     assessment called one-page-per-CVE "a huge renewing long tail"). SE
     Ranking US, treg call `1a2a0ca7…`: "log4shell" 440 / KD 38, "log4j
     vulnerability" 440 / KD 50, "fortinet vulnerability" 260 / KD 36, "palo
     alto vulnerability" 170 / KD 21, "moveit vulnerability" 170 / KD 34;
     raw IDs (`cve-2024-3094`, `-6387`, `-4577`, …) returned no data for 9 of
     10, and monthly averages hide disclosure spikes. Planned as thoralox
     PRD v2 (named exploited-vuln pages, vendor hubs, new-KEV fast path).
     Held back until v1.I lifts its site-wide noindex.
  2. caringbeds.com — hospital bed rentals; its own docs call the demand
     wide open; 1 page today → a cluster (rent vs buy, Medicare, types, by
     city/state).
  3. permittruck.xyz — "food truck permit [state/city]" is the cottagefoodmap
     pattern; move off `.xyz` first.
  4. dunam.co — retarget from the product to fire-extinguisher inspection
     requirements; 242 of its 352 impressions already sit at positions 5–20
     (quickest test).
  5. bppvcoach.com — large vertigo / Epley demand around the tool; health
     topic, so citations matter.
  - After technical fixes: voltloop.site (soft-404, homepage only),
    anglicanpath.org (63 days old), keralavotemap.site (election-timed;
    soft-404, `.site`).
- **Low ceiling — narrow B2B products:** dropaudit, agesdk / disclosur,
  pqhorizon, iotbastion, markpdf, mdburst, drdebug, meetwhen, threadradar,
  retouchlint, mcpscan. A few cited explainers on the regulation each one
  answers (SB 361, AB 1043, CMMC, post-quantum deadlines, photo-disclosure
  rules), not a big push.
  - **retouchlint: big audience, small search demand for its angle**
    (keyword data, SE Ranking US, 2026-11-23, treg call `031ed089…`). The
    audience (agents, brokers, listing photographers) is large, but the
    photo-rules / compliance searches barely register: "mls photo
    requirements" 40/mo, "mls photo rules" 20; no data for "virtual staging
    disclosure", "is virtual staging legal", "real estate photo compliance",
    "ab 723", "zillow photo requirements" and similar (no data = very small
    or unknown, not proven zero). Broad topics are big but commercial and
    contested: "real estate photography" 9,900 (KD 37), "virtual staging"
    4,400 (KD 59). The realistic room is low-KD editing-technique terms:
    "listing photos" 320 (KD 8), "mls photos" 140 (KD 25), "virtual
    twilight" 110 (KD 7), "twilight real estate photos" 110, seasonal to 480
    (KD 12), "virtual staging ai" 180 (KD 35, was 810 earlier in 2026).
    Lesson: size the *angle's* searches, not the audience.
- **Broad but very competitive:** kwizicle (quizzes), cricketfansite,
  homeloom, dearreels.

## Open questions

- **What separates the stuck sites from the indexed ones beyond soft-404?**
  calcengine.site, civictools.app and cricketfansite.com return proper 404s
  and are still stuck. External links don't separate the groups (2026-11-16:
  most sites in both groups have none in Google's referrer data); age and
  homepage crawl cadence (~monthly) look similar too.
- **Does "Request indexing" move an unknown URL on a site Google seems to
  have deprioritised?** Untested — planned on calcengine.site
  (`growth.md` 2026-11-21).
- **Is a low-demand page batch a site-wide crawl-priority penalty?**
  calcengine.site hypothesis; day-60 / day-90 checkpoints 2026-12-04 /
  2027-01-03.
