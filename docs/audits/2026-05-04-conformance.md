# Workspace Conformance Audit — 2026-05-04

**31 projects audited** (excluding To-be-deleted-immediately category).

## Most common failures across the workspace

| Rule | Failing | % of projects |
|---|---:|---:|
| `has-makefile` | 19 | 61% |
| `has-growth-log` | 19 | 61% |
| `own-git-repo` | 18 | 58% |
| `platform-declared` | 13 | 42% |
| `prompts-md-format` | 11 | 35% |
| `live-site` | 7 | 23% |

## Per-project status (sorted: cleanest first)

| Project | Verdict | Pass | Fail | Skip | Top failures |
|---|---|---:|---:|---:|---|
| carrepairsite.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| dunam.co | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| keralavotemap.site | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| lamill.us | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| maslist.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| navodayansonline.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| nosapta.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| plaira.io | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| veezp.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| vijocherian.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| virtually.co.in | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| yesuinnu.com | Misconfigured | 1 | **1** | 7 | `own-git-repo` |
| calcengine.site | Quiet | 7 | **2** | 0 | `has-makefile`, `has-growth-log` |
| homeloom.app | Quiet | 7 | **2** | 0 | `has-makefile`, `has-growth-log` |
| lamillrentals.com | Active | 7 | **2** | 0 | `has-makefile`, `has-growth-log` |
| washcalc.app | Quiet | 7 | **2** | 0 | `has-makefile`, `has-growth-log` |
| cricketfansite.com | Active | 6 | **3** | 0 | `has-makefile`, `has-growth-log`, `platform-declared` |
| isitholiday.today | Active | 6 | **3** | 0 | `has-makefile`, `has-growth-log`, `platform-declared` |
| kwizicle.com | Active | 6 | **3** | 0 | `has-makefile`, `has-growth-log`, `live-site` |
| lamill.io | Active | 6 | **3** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log` |
| civictools.app | Active | 5 | **4** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log`, `platform-declared` |
| csinorcal.church | Active | 5 | **4** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log`, `platform-declared` |
| hybridautopart.com | Active | 5 | **4** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log`, `platform-declared` |
| voltloop.site | Active | 5 | **4** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log`, `platform-declared` |
| airsucks.com | Misconfigured | 4 | **5** | 0 | `own-git-repo`, `has-makefile`, `has-growth-log`, `platform-declared` … |
| iotbastion.com | Fresh | 4 | **5** | 0 | `prompts-md-format`, `has-makefile`, `has-growth-log`, `platform-declared` … |
| streamsgalaxy.com | Misconfigured | 4 | **5** | 0 | `own-git-repo`, `prompts-md-format`, `has-makefile`, `has-growth-log` … |
| iotnews.today | Misconfigured | 3 | **6** | 0 | `own-git-repo`, `prompts-md-format`, `has-makefile`, `has-growth-log` … |
| linkedcsi.live | Misconfigured | 3 | **6** | 0 | `own-git-repo`, `prompts-md-format`, `has-makefile`, `has-growth-log` … |
| thoralox.com | Misconfigured | 3 | **6** | 0 | `own-git-repo`, `prompts-md-format`, `has-makefile`, `has-growth-log` … |
| whizgraphs.com | Misconfigured | 3 | **6** | 0 | `own-git-repo`, `prompts-md-format`, `has-makefile`, `has-growth-log` … |

## Triage observations

- **own-git-repo failures** are the highest-leverage to fix — projects tracked by parent /sites/.git can't make progress on most other rules until isolated. Auto-fixable in v4.D via guided git migration.
- **has-makefile** is the most common failure (61%) — most projects predate the forwarder convention. v4.D auto-fix scaffolds the standard Makefile.
- **has-growth-log** (61%) is brand new (added today); auto-fixable via v4.D scaffolding the dated-H2 template.
- **Cleanest projects** (`calcengine.site`, `homeloom.app`, `lamillrentals.com`, `washcalc.app`) — only missing Makefile + growth log; these get to clean with one v4.D run each.
- The 4 projects clean enough to be the first `portfolio project fix` candidates once v4.D ships.
