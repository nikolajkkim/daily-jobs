#!/usr/bin/env python3
"""
watch.py — check every company on watch/watchlist.json for new DS/ML internships.

Reads each company's public job feed (Greenhouse, Lever, Ashby, SmartRecruiters
or Workday), keeps titles that look like data science / ML / AI internships in
the US or remote, and remembers when each posting was first seen.

Writes:
  watch/seen.json        every matching posting ever seen, with first-seen date
  watch/candidates.json  matches first seen in the last few days that aren't on the site yet
  watch/report.json      per-company feed status (ok / not found / error) for upkeep

Runs daily on GitHub Actions (.github/workflows/watch.yml). Standard library only.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "watch"
NEW_WINDOW_DAYS = 3
UA = {"User-Agent": "daily-jobs-watch/1.0 (personal job tracker)"}

ROLE = re.compile(r"\b(data|machine learning|ml|ai|artificial intelligence|applied scien\w*|research scien\w*|"
                  r"analytics|deep learning|computer vision|nlp|llm|quantitative research\w*|decision scien\w*)\b", re.I)
INTERN = re.compile(r"\b(intern|interns|internship|co-?op)\b", re.I)
SKIP_TITLE = re.compile(r"\b(ph\.?d\.?(?! or)|data cent(er|re)|data entry|legal|marketing|sales|recruit\w*|hr\b)", re.I)
NON_US = re.compile(r"\b(london|uk|united kingdom|ireland|dublin|india|bangalore|bengaluru|hyderabad|toronto|canada|"
                    r"vancouver|montreal|germany|berlin|munich|france|paris|amsterdam|netherlands|singapore|"
                    r"hong kong|tokyo|japan|sydney|australia|china|shanghai|beijing|israel|tel aviv|poland|"
                    r"warsaw|brazil|mexico|spain|madrid|switzerland|zurich|korea|seoul|taiwan|sweden|stockholm)\b", re.I)
US = re.compile(r"\b(united states|usa|us|remote|new york|nyc|ny|california|ca|san francisco|sf|bay area|"
                r"los angeles|la|seattle|wa|chicago|il|boston|ma|austin|tx|texas|denver|co|atlanta|ga|"
                r"washington|dc|miami|fl|philadelphia|pa|san jose|palo alto|mountain view|menlo park|"
                r"sunnyvale|redmond|cambridge|jersey city|nj|stamford|ct|pittsburgh|irvine|san diego|"
                r"santa monica|culver city|carlsbad|dallas|houston|raleigh|portland|salt lake)\b", re.I)


def fetch_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA)
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def iso(ts):
    """Normalize a timestamp (ISO string or epoch ms) to YYYY-MM-DD, or None."""
    if ts is None or ts == "":
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None

# ---------------------------------------------------------------- feeds
# Each returns a list of {title, location, url, posted}

def greenhouse(c):
    d = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs")
    return [{"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", ""), "posted": iso(j.get("first_published") or j.get("updated_at"))}
            for j in d.get("jobs", [])]


def lever(c):
    d = fetch_json(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json")
    out = []
    for j in d:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        out.append({"title": j.get("text", ""), "location": " / ".join(l for l in locs if l),
                    "url": j.get("hostedUrl", ""), "posted": iso(j.get("createdAt"))})
    return out


def ashby(c):
    d = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}")
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
        if j.get("isRemote"):
            locs.append("Remote")
        out.append({"title": j.get("title", ""), "location": " / ".join(l for l in locs if l),
                    "url": j.get("jobUrl", ""), "posted": iso(j.get("publishedAt"))})
    return out


def smartrecruiters(c):
    out, offset = [], 0
    while offset < 500:
        d = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings?q=intern&limit=100&offset={offset}")
        for j in d.get("content", []):
            loc = j.get("location") or {}
            out.append({"title": j.get("name", ""),
                        "location": ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
                                    + (" / Remote" if loc.get("remote") else ""),
                        "url": f"https://jobs.smartrecruiters.com/{c['slug']}/{j.get('id')}",
                        "posted": iso(j.get("releasedDate"))})
        if len(d.get("content", [])) < 100:
            break
        offset += 100
    return out


def workday(c):
    host, tenant, site = c["host"], c["tenant"], c["site"]
    out = []
    for q in ("intern data", "intern machine learning", "intern AI"):
        d = fetch_json(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                       {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q})
        for j in d.get("jobPostings", []):
            posted = None
            m = re.search(r"Posted (Today|Yesterday|(\d+)\+? Days? Ago)", j.get("postedOn", ""), re.I)
            if m:
                days = 0 if m.group(1).lower() == "today" else 1 if m.group(1).lower() == "yesterday" else int(m.group(2))
                posted = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            out.append({"title": j.get("title", ""), "location": j.get("locationsText", ""),
                        "url": f"https://{host}/en-US/{site}{j.get('externalPath', '')}", "posted": posted})
    return out


FEEDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby,
         "smartrecruiters": smartrecruiters, "workday": workday}

# ---------------------------------------------------------------- filtering

def wanted(job):
    t, loc = job["title"], job.get("location") or ""
    if not (INTERN.search(t) and ROLE.search(t)) or SKIP_TITLE.search(t):
        return False
    if loc and NON_US.search(loc) and not US.search(loc):
        return False
    return True


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def check(c):
    try:
        jobs = FEEDS[c["ats"]](c)
        hits = [dict(j, company=c["name"], category=c.get("category", ""), ats=c["ats"]) for j in jobs if wanted(j)]
        return c, {"status": "ok", "open_jobs": len(jobs), "matches": len(hits)}, hits
    except urllib.error.HTTPError as e:
        return c, {"status": "not found" if e.code == 404 else f"http {e.code}"}, []
    except Exception as e:  # network, bad JSON, schema change
        return c, {"status": f"error: {type(e).__name__}: {str(e)[:120]}"}, []


def main():
    watchlist = json.loads((WATCH / "watchlist.json").read_text())["companies"]
    seen_path = WATCH / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    site = json.loads((ROOT / "jobs.json").read_text()).get("jobs", [])
    on_site_urls = {j.get("url") for j in site}
    on_site_keys = {(norm(j.get("company")).split(" ")[0], norm(j.get("title"))) for j in site}

    today = datetime.now(timezone.utc).date().isoformat()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, watchlist))

    report = {}
    for c, status, hits in results:
        report[c["name"]] = dict(status, ats=c["ats"], slug=c.get("slug") or c.get("tenant"))
        for h in hits:
            key = h["url"] or f"{h['company']}|{h['title']}"
            if key not in seen:
                seen[key] = dict(h, first_seen=today)
            else:
                seen[key].update({k: h[k] for k in ("title", "location", "posted")})
                seen[key]["last_seen"] = today
            seen[key]["last_seen"] = today

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=NEW_WINDOW_DAYS)).isoformat()
    candidates = []
    for key, s in seen.items():
        if s.get("last_seen") != today:          # no longer listed
            continue
        fresh = s["first_seen"] >= cutoff or (s.get("posted") or "") >= cutoff
        on_site = s["url"] in on_site_urls or (norm(s["company"]).split(" ")[0], norm(s["title"])) in on_site_keys
        if fresh and not on_site:
            candidates.append(s)
    candidates.sort(key=lambda s: (s.get("posted") or s["first_seen"]), reverse=True)
    candidates = candidates[:40]  # keep the morning scan's reading short

    first_run = not seen_path.exists()
    seen_path.write_text(json.dumps(seen, indent=1, ensure_ascii=False) + "\n")
    (WATCH / "candidates.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "note": "First run: everything currently open counts as new." if first_run else
                f"Postings first seen (or posted) in the last {NEW_WINDOW_DAYS} days and not yet on the site.",
        "candidates": candidates}, indent=1, ensure_ascii=False) + "\n")
    ok = sum(1 for r in report.values() if r["status"] == "ok")
    (WATCH / "report.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "feeds_ok": ok, "feeds_total": len(report), "companies": report}, indent=1, ensure_ascii=False) + "\n")
    print(f"{ok}/{len(report)} feeds ok · {sum(r.get('matches', 0) for r in report.values())} matching postings · {len(candidates)} candidates")
    for name, r in sorted(report.items()):
        if r["status"] != "ok":
            print(f"  {name}: {r['status']}")


if __name__ == "__main__":
    sys.exit(main())
