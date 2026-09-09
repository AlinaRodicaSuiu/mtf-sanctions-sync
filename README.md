# Monaco Trade Forum — Sanctions data sync

This small repo does one job: keep the Monaco Trade Forum Sanctions
Checker's data current, automatically, with no manual downloads.

Daily (and on demand via the Actions tab), a GitHub Actions workflow:

1. Downloads the current OFAC SDN list and UK Sanctions List (FCDO)
   directly from their official sources.
2. Normalises and deduplicates them into the Monaco Trade Forum schema
   (`scripts/build_sanctions_data.py`), reusing existing entity ids so
   history stays attached to the same entity across syncs.
3. Commits the updated `data/sanctions-list.json` and
   `data/sanctions-changelog.json` back to this repo — a free, permanent
   audit trail of every sync.
4. Pushes those same two files to Cloudflare Workers KV, which is what
   monacotradeforum.com actually reads at request time.

This repo is **separate from the website's own deploy folder** — it is
never drag-and-dropped into Cloudflare Pages. Its only output is the two
JSON files it writes into Cloudflare KV.

Full architecture, the Cloudflare Workers Free-plan constraint that led to
this design, and the one-time setup steps (GitHub secrets, Cloudflare KV
namespace, API token scope) are documented in
`claude/arhitectura-mtf-sanctions-checker.md` in the Monaco Trade Forum
Claude project.

Run it manually any time from GitHub → **Actions** → **Sync Monaco Trade
Forum sanctions data** → **Run workflow**.
