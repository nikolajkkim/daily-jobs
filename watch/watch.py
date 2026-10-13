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

import hashlib
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
NEW_WINDOW_DAYS = 2     # "new" = posted (or first seen, when no date) within this many days
BROWSE_MAX_AGE_DAYS = 45
UA = {"User-Agent": "daily-jobs-watch/1.0 (personal job tracker)"}

ROLE = re.compile(r"\b(data|machine learning|ml|ai|artificial intelligence|applied scien\w*|research scien\w*|"
                  r"analytics|deep learning|computer vision|nlp|llm|decision scien\w*|applied ai)\b", re.I)
INTERN = re.compile(r"\b(intern|interns|internship|co-?op)\b", re.I)
SKIP_TITLE = re.compile(r"\b(ph\.?d\.?(?! or)|data cent(er|re)|data entry|legal|marketing|sales|recruit\w*|hr\b|audit|people\w*|ux|business analytics|data analyst|quantitative (research|trad)\w*|quant (research|trad)\w*|toronto)", re.I)
BACHELORS = re.compile(r"\b(bs|b\.s\.?|ba|bachelor'?s?|undergrad\w*|freshman|sophomore|rising (junior|senior)s?)\b", re.I)
MASTERS = re.compile(r"\b(ms|m\.s\.?|master'?s?|graduate|grad|mba|bs/ms|ba/ms)\b", re.I)
NON_US = re.compile(r"\b(london|uk|united kingdom|ireland|dublin|india|bangalore|bengaluru|hyderabad|toronto|canada|"
                    r"vancouver|montreal|germany|berlin|munich|france|paris|amsterdam|netherlands|singapore|"
                    r"hong kong|tokyo|japan|sydney|australia|china|shanghai|beijing|israel|tel aviv|poland|"
                    r"warsaw|brazil|mexico|spain|madrid|switzerland|zurich|korea|seoul|taiwan|sweden|stockholm|gurgaon|gurugram|"
                    r"pune|mumbai|delhi|chennai|ontario|europe|emea|apac|berlin|belgrade|serbia|lisbon|portugal|prague|budapest|romania|ukraine|kyiv|nigeria|kenya|egypt|vietnam|philippines|manila|indonesia|malaysia|thailand|argentina|colombia|chile)\b", re.I)
US_STRONG = re.compile(r"\b(united states|usa|new york|nyc|california|san francisco|bay area|los angeles|seattle|chicago|"
                       r"boston|austin|texas|denver|atlanta|miami|philadelphia|san jose|palo alto|mountain view|menlo park|"
                       r"sunnyvale|redmond|jersey city|stamford|pittsburgh|irvine|san diego|santa monica|culver city|carlsbad|"
                       r"dallas|houston|raleigh|cary|portland|salt lake|ponte vedra|olathe|washington, d)", re.I)
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


SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
STATE = re.compile(r",\s*(A[KLRZ]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b")


def us_location(loc):
    return bool(US_STRONG.search(loc) or STATE.search(loc) or re.search(r"remote in usa|\busa\b|united states", loc, re.I))


def simplify_listings():
    """Simplify's community-maintained internship list (thousands of companies, with posting dates)."""
    data = fetch_json(SIMPLIFY_URL)
    cutoff = datetime.now(timezone.utc) - timedelta(days=BROWSE_MAX_AGE_DAYS)
    out = []
    for x in data:
        if not x.get("active") or x.get("is_visible") is False:
            continue
        posted_dt = datetime.fromtimestamp(x.get("date_posted") or 0, tz=timezone.utc)
        if posted_dt < cutoff:
            continue
        terms = x.get("terms") or []
        if terms and not any("2027" in t or t == "N/A" for t in terms):
            continue
        degrees = x.get("degrees") or []
        if degrees and "Master's" not in degrees:          # bachelor's-only, PhD-only, etc.
            continue
        title = x.get("title", "")
        if not ROLE.search(title) or SKIP_TITLE.search(title) or (BACHELORS.search(title) and not MASTERS.search(title)):
            continue
        locs = [l for l in (x.get("locations") or []) if us_location(l)]
        if not locs:
            continue
        out.append({"title": title, "location": " / ".join(locs[:4]) + (" + more" if len(locs) > 4 else ""),
                    "url": x.get("url", ""), "posted": posted_dt.date().isoformat(),
                    "company": x.get("company_name", ""), "terms": terms, "degrees": degrees,
                    "category": "finance" if "Quant" in (x.get("category") or "") else ""})
    return out


FEEDS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby,
         "smartrecruiters": smartrecruiters, "workday": workday}

# ---------------------------------------------------------------- filtering

def wanted(job):
    t, loc = job["title"], job.get("location") or ""
    if not (INTERN.search(t) and ROLE.search(t)) or SKIP_TITLE.search(t):
        return False
    if BACHELORS.search(t) and not MASTERS.search(t):   # bachelor's-only postings
        return False
    canada = re.search(r",\s*(on|bc|qc|ab)\s*(,|$)", loc, re.I)
    if loc and (NON_US.search(loc) or canada) and not US_STRONG.search(loc):
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
    site_data = json.loads((ROOT / "jobs.json").read_text())
    site = site_data.get("jobs", []) + site_data.get("browse", [])
    on_site_urls = {j.get("url") for j in site}
    on_site_keys = {(norm(j.get("company")).split(" ")[0], norm(j.get("title"))) for j in site}

    today = datetime.now(timezone.utc).date().isoformat()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, watchlist))

    known_cat = {c["name"].lower(): c.get("category", "") for c in watchlist}
    try:
        simp = simplify_listings()
        results.append(({"name": "Simplify internship list", "ats": "simplify", "slug": "SimplifyJobs/Summer2027-Internships"},
                        {"status": "ok", "open_jobs": len(simp), "matches": len(simp)},
                        [dict(j, ats="simplify", category=j["category"] or known_cat.get(j["company"].lower(), "tech")) for j in simp]))
    except Exception as e:
        results.append(({"name": "Simplify internship list", "ats": "simplify", "slug": "SimplifyJobs/Summer2027-Internships"},
                        {"status": f"error: {type(e).__name__}: {str(e)[:120]}"}, []))

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
    old_cutoff = (datetime.now(timezone.utc).date() - timedelta(days=BROWSE_MAX_AGE_DAYS)).isoformat()
    candidates, browse, dup = [], [], set()
    # Feed entries first (direct company links), then Simplify, so duplicates keep the direct link.
    order = sorted(seen.items(), key=lambda kv: kv[1].get("ats") == "simplify")
    for key, s in order:
        if s.get("last_seen") != today:                      # no longer listed
            continue
        if s.get("ats") != "simplify" and not wanted(s):     # filtered out by newer rules
            continue
        posted = s.get("posted") or ""
        if posted and posted < old_cutoff:
            continue
        ident = (norm(s["company"]).split(" ")[0] if s["company"] else "", norm(s["title"]))
        if ident in dup:
            continue
        dup.add(ident)
        fresh = posted >= cutoff if posted else s["first_seen"] >= cutoff
        on_site = s["url"] in on_site_urls or ident in on_site_keys
        if fresh and not on_site:
            candidates.append(s)
        if not on_site:
            browse.append({"id": "w-" + hashlib.sha1(key.encode()).hexdigest()[:12], "company": s["company"],
                           "title": s["title"], "location": s.get("location", ""), "url": s["url"],
                           "source": {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby",
                                      "smartrecruiters": "SmartRecruiters", "workday": "Workday",
                                      "simplify": "Simplify list"}.get(s.get("ats"), "Company site"),
                           "category": s.get("category", ""), "posted": s.get("posted"), "found": s["first_seen"]})
    candidates.sort(key=lambda s: (s.get("posted") or s["first_seen"]), reverse=True)
    candidates = candidates[:60]  # keep the morning scan's reading short

    browse.sort(key=lambda b: (b.get("posted") or b["found"]), reverse=True)
    (WATCH / "browse.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "jobs": browse}, indent=1, ensure_ascii=False) + "\n")
    first_run = not seen_path.exists()
    seen_path.write_text(json.dumps(seen, indent=1, ensure_ascii=False) + "\n")
    (WATCH / "candidates.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "note": "First run: everything currently open counts as new." if first_run else
                f"Postings posted in the last {NEW_WINDOW_DAYS} days (or first seen then, when no date is known) and not yet on the site.",
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
