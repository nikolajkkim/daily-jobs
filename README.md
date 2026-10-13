# Daily Jobs

A daily list of data science and ML internships matched to my resume, so I can apply early.

- `index.html` is the site (GitHub Pages).
- `jobs.json` holds the jobs. The **Morning scan** workflow (`.github/workflows/scan.yml`) refreshes the job feeds and runs Claude early each morning to add up to 5 daily picks plus extra Browse finds. Instructions live in `scan/PROMPT.md`. Run it by hand from the Actions tab (Morning scan → Run workflow).
- `watch/` holds the company watchlist and the feed checker (`watch/watch.py`).
- "Mark applied" and "Skip" are saved in your browser, so they're per device.

## Sync with tracker.xlsx (optional)

`config.js` holds the Supabase project URL and publishable key. When set, you can sign in on the site
(email link, only your address is allowed) and "Mark applied" flows into the local tracker through
`career-tailor-v2/daily-jobs-sync/sync.py`, while tracker statuses flow back here. With `config.js`
empty, marks are saved in the browser only.
