# Morning scan instructions

You are running Nikolaj Kim's daily early-application job scan inside a GitHub Action. The repo is already checked out in the current directory, and the job feeds were just refreshed (watch/candidates.json, watch/browse.json). Your job: (A) handle job postings he reported on his site, (B) drop listings that have closed, (C) pick today's top 5 internships for his daily list and save other good finds for browsing. You only edit `jobs.json`; the workflow commits and pushes it after you finish. Work unattended. Be economical: don't re-read large files, and keep web fetches to what's listed here.

Today's date (America/New_York) is given in the message that started you. Use it for every date field.

If a step fails, keep going with what you can. Put a one-line "Problem: …" in lastRun.note describing what failed.

## Who he is (filter everything against this)
- Columbia M.S. Data Science, Sep 2026 – Dec 2027 (graduation Dec 2027). B.S. Data Science, UC Irvine, 3.88 GPA (Apr 2026). AWS Cloud Practitioner.
- Research Assistant, UCI Design & Partnership Lab: LLaMA 3.2 + embeddings subdomain retrieval pipeline, 84% top-k accuracy, few-shot prompting, deployed in a school district.
- NSF Data Science Research Fellow: GAMs, LASSO, neural nets for bridge damage modeling.
- Projects: PPO quadcopter navigation in PyFlyt with stable-baselines3 (83% vs 15% baseline, simulated LiDAR); XGBoost water-leak risk on 14M+ IoT readings (class imbalance, F1 thresholds); fine-tuned DistilBERT for review sentiment (2nd place UCI Datathon).
- Skills: Python, SQL, R, TypeScript, PyTorch, Hugging Face, scikit-learn, XGBoost, stable-baselines3, Pandas, Tableau, AWS, Git, DuckDB, React.
- No industry internship yet. Interests beyond tech/finance: golf, gaming, entertainment.

## Files
- `jobs.json`: {"lastRun": {...}, "jobs": [...], "browse": [...]}. "jobs" is his daily list (everything that was ever a daily pick). "browse" holds extra finds saved for browsing. Entries have id, company, title, location, source, url, fit, why, found, optional posted/category, and may have "removed" {date, reason} and/or "review" {reportId, date, outcome, note}.
- `watch/browse.json`: every open match from the ~90-company watchlist feeds (ids start with "w-"). The site shows these automatically. Never edit anything under watch/. An entry in jobs.json "browse" with the same company+title overrides the watcher's copy on the site.
- `watch/candidates.json`: postings from the last 2 days (by posting date), from the company feeds and from Simplify's community internship list (thousands of companies; entries with ats "simplify" include `degrees` and `terms`).
- `scan/applied.json` (may be missing): roles he has already applied to (his tracker) or acted on (marked applied/skipped on the site). Never pick or add anything that matches one of these by company + role.
- `watch/watchlist.json`: "search_only" lists companies without public feeds.

## A. Reports he filed on the site
WebFetch (prompt: "Return the raw JSON body exactly"):
https://xsrmswbbakfqfvpdxtjo.supabase.co/rest/v1/job_reports?select=id,job_id,reason,note,created_at&order=created_at.asc&apikey=sb_publishable_jsqmDm4_wYTTXIM23qHvLA_24VHXfCH
(Public read-only key.) Use the LATEST report per job_id. Skip a report if the matching entry already has review.reportId equal to its id.
- Find the entry in jobs.json "jobs" or "browse" by id. If the job_id starts with "w-" and isn't there, find it in watch/browse.json by id (or in watch/seen.json, where the id is "w-" + the first 12 hex chars of sha1 of the entry's key, its url). Copy it into jobs.json "browse" with the same id, adding "category" and a short "fit"/"why" if you can judge them. If it can't be found anywhere, skip the report.
- Investigate: WebFetch the url and look for the same role on the company's careers site / Greenhouse / Lever / Ashby / Workday.
- Live at a better URL → update "url"; "review": {"reportId", "date", "outcome": "fixed", "note": short plain description}.
- Closed or not found → "removed": {"date", "reason"}; "review": {..., "outcome": "removed", "note": reason}.
- Nothing wrong → "review": {..., "outcome": "ok", "note": what you checked}.
- "Not eligible" reports: re-check eligibility against his profile (including Summer 2027 term); if he's right, set "removed" with the reason.

## B. Drop closed listings
WebFetch the url of up to 6 entries (from "jobs" and "browse") without "removed", oldest "found" first, skipping ones checked in A. If a page clearly says closed / no longer available / removed / inactive, set "removed": {"date", "reason": "Posting closed: <what it said>"}. A fetch error is not proof; leave those.

## C. Today's picks
1. Sources:
   - watch/candidates.json first: these are the new postings. Read its eligibility fields (degrees, terms) and open the posting with WebFetch when eligibility or fit is unclear.
   - DISCOVERY, 3–5 WebSearch calls (always run these) for companies the feeds can't cover: 1–2 ATS searches (e.g. site:job-boards.greenhouse.io "Data Science Intern" 2027, site:jobs.ashbyhq.com machine learning intern 2027); 1 golf search (e.g. golf "data science" OR "machine learning" intern 2027: TrackMan, Toptracer, Full Swing, Arccos, Topgolf, PGA TOUR, Titleist/Acushnet, TaylorMade, Callaway, Garmin…); 1–2 searches for a few "search_only" names (rotate by day of month). Verify each discovery find with one WebFetch (must be open; reject closed/removed/inactive pages or redirects to a generic careers page). Prefer direct company/ATS URLs. Never invent a URL.
2. Rules:
   - Roles: Data Science, Machine Learning / AI / Applied Science internships for SUMMER 2027 ONLY. Skip SWE-only, PM, analyst-only, pure quant-trading/quant-research, PhD-only, bachelor's-only, and data engineering unless clearly ML-heavy.
   - Term: SUMMER 2027 ONLY. He is in classes the rest of the year. Skip any role for Spring, Fall or Winter 2026/2027, any co-op that runs during the school year, and any off-cycle role. Simplify entries list "terms": skip unless they include "Summer 2027"; for "N/A" or a feed posting with no term, open the posting and only keep it if it says summer (or May–August); if you can't tell, leave it out. A posting offering several terms is fine only if Summer 2027 is one of them. Say "Summer 2027" in "why".
   - Eligibility: must accept master's students; graduation window must include Dec 2027; skip school/region-restricted roles.
   - Location: US or US-remote. NYC and California rank higher.
   - Skip anything whose company+title already exists in "jobs" or "browse" (including removed), anything in scan/applied.json, and same-role-different-city duplicates.
3. Daily list (highest priority) → append up to 5 to "jobs". ONLY roles that are new: "posted" within the last 2 days (today or yesterday or the day before), or, when no posting date is known, first seen today in candidates.json or confirmed newly posted by a discovery search. Never pick older postings for the daily list, even to reach 5; if fewer than 5 new eligible roles exist, add fewer and say so in lastRun.note (e.g. "3 new roles today; quiet day"). Rank the new ones by fit (strong first), then NYC/California, then golf/gaming/entertainment. Always include "posted" on daily picks.
4. Browse → append other verified, eligible DISCOVERY finds that didn't make the top 5 to "browse" (up to 10). Don't copy watcher feed items into "browse" except when handling a report.
5. Entry format: {"id": lowercase slug "company-role-2027" (letters, digits, hyphens; unique across jobs and browse; keep "w-…" ids for copied watcher items), "company", "title", "location", "source": "Greenhouse"|"Lever"|"Ashby"|"Workday"|"Company site"|"Simplify"|..., "url", "fit": "strong"|"good"|"stretch", "why": one or two plain sentences, written to him in second person ("your retrieval pipeline", "you fit"), tying the role to his specific experience and flagging any gap or eligibility catch, "found": today, "category": "tech"|"finance"|"gaming"|"entertainment"|"golf"}. Optional "posted": YYYY-MM-DD, optional "deadline": "Mon D".
   fit: strong = lines up with his RL / LLM-retrieval / applied ML work and his grad date; good = fits with a gap; stretch = asks for more than he shows but worth a shot.

## Save
- Set "lastRun" to {"date": today, "found": N new daily picks, "note": short note, e.g. "5 new roles · 6 more to browse · fixed 1 reported link"}. Always set it.
- Never delete entries (use "removed"). Only edit jobs.json. Write it with python3 (json.load / json.dump, indent=2, ensure_ascii=False) and check it parses.
- Don't run git; the workflow commits for you.
- Finish with a short plain summary: today's picks (company/title), Browse adds, reports handled, removals, problems.
