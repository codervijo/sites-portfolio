# sites-portfolio

A personal CLI (`lamill`) for managing a domain portfolio + sibling
`sites/<domain>/` workspace. Domain lifecycle, project bootstrap,
universal-check catalog, live SEO probes, GSC integration.

## `lamill settings gsc recrawl`

Reports which sitemap URLs Google has re-crawled since a baseline
timestamp — useful for confirming that a deploy was picked up by
Search Console.

```bash
# Default — every URL in the site's sitemap, baseline = HEAD commit time:
lamill settings gsc recrawl --site washcalc.app

# Explicit baseline + URL list:
lamill settings gsc recrawl --site washcalc.app \
    --since 2026-05-15T12:39Z \
    --urls /tmp/changed-urls.txt
```

Output is a markdown table (printed to stdout AND appended to
`sites/<domain>/docs/growth.md` under a dated heading) showing per-URL
last-crawl time, page-fetch state, indexing state, and a re-crawled-✓
column.

### Quotas + the Indexing API caveat

This command uses **`urlInspection.index.inspect`** (a method on the
existing `webmasters.readonly` OAuth scope — no widening). Google
limits that endpoint to roughly **2000 calls per property per day**.
Default URL set comes from the site's sitemap (typically 5–50 URLs
for portfolio-scale sites), so a few runs a day is fine. For
larger sites, batch the URLs explicitly via `--urls`.

**This command cannot trigger a re-crawl.** Google's *Indexing API*
(`indexing.googleapis.com` `urlNotifications.publish`) is officially
restricted to **`JobPosting` and `BroadcastEvent`** content. Using it
for general web pages violates Google's Terms of Service, and Google
silently ignores the submissions. For general pages, you still have
to click **Request Indexing** in Search Console manually.

`lamill settings gsc recrawl` is read-only — it reports status, it
does not change indexing.
