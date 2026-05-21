"""
GitWire Engine — scraper.py
Fetches trending GitHub repos, generates editorial copy via Gemini,
and writes weekly.json for the public gitwire repo.

Mirrors the logic in gitwire.html's generateEdition() exactly so
renderEdition() on the frontend consumes the output without changes.
"""

import os
import json
import math
import time
import random
import datetime
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")   # optional but recommended

GEMINI_MODEL   = "gemini-2.5-flash"
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GH_SEARCH_URL  = "https://api.github.com/search/repositories"

OUTPUT_FILE    = "weekly.json"   # written to CWD; workflow moves it to public repo

# ── HELPERS ───────────────────────────────────────────────────────────────────

def gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def edition_number():
    """Mirrors getEditionNumber() in the HTML."""
    origin = datetime.date(2025, 1, 6)   # first Monday of 2025
    today  = datetime.date.today()
    weeks  = math.floor((today - origin).days / 7) + 1
    return str(max(1, weeks)).zfill(3)


def week_range():
    """Mirrors getWeekRange() in the HTML — Mon–Sun of the current week."""
    today   = datetime.date.today()
    monday  = today - datetime.timedelta(days=(today.weekday()))
    sunday  = monday + datetime.timedelta(days=6)
    def fmt(d):
        return d.strftime("%-d %b").lstrip("0")   # "5 May" style
    return f"{fmt(monday)} – {fmt(sunday)}, {sunday.year}"


# ── GITHUB FETCH ──────────────────────────────────────────────────────────────

def fetch_trending_repos(days_ago=7, per_page=25):
    since = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
    q     = f"created:>{since} stars:>10"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": per_page}
    r = requests.get(GH_SEARCH_URL, headers=gh_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("items", [])


def fetch_resurrection_repo():
    today    = datetime.date.today()
    since    = (today - datetime.timedelta(days=180)).isoformat()
    until    = (today - datetime.timedelta(days=30)).isoformat()
    recent   = (today - datetime.timedelta(days=7)).isoformat()
    q = f"created:{since}..{until} stars:>50 pushed:>{recent}"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": 10}
    r = requests.get(GH_SEARCH_URL, headers=gh_headers(), params=params, timeout=20)
    if not r.ok:
        return None
    items = r.json().get("items", [])
    if not items:
        return None
    return random.choice(items[:min(5, len(items))])


def slim_repo(r):
    """
    Return only the fields renderEdition() actually reads, keeping weekly.json lean.
    Matches the GitHub API repo object shape the frontend expects.
    """
    return {
        "full_name":        r.get("full_name", ""),
        "description":      r.get("description", ""),
        "html_url":         r.get("html_url", ""),
        "stargazers_count": r.get("stargazers_count", 0),
        "forks_count":      r.get("forks_count", 0),
        "language":         r.get("language", ""),
        "topics":           r.get("topics", []),
        "created_at":       r.get("created_at", ""),
        "pushed_at":        r.get("pushed_at", ""),
    }


# ── GEMINI CALLS ─────────────────────────────────────────────────────────────

def call_gemini(prompt, retries=3):
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    for attempt in range(retries):
        try:
            r = requests.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json=payload,
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            if attempt < retries - 1:
                print(f"  Gemini retry {attempt + 1} after error: {e}")
                time.sleep(4)
            else:
                raise
    return ""


SIGNAL_PROMPT = """You are the lead writer for GitWire, a weekly GitHub intelligence publication. Write an engaging editorial article about this GitHub repository that was trending this week.

Repository: {full_name}
Description: {description}
Stars: {stars}
Language: {language}
Topics: {topics}
URL: {url}

Write a compelling 3-paragraph editorial article (200-250 words).
- First paragraph: what this is and why it matters RIGHT NOW
- Second paragraph: the broader context — what problem space, what trend
- Third paragraph: why developers and tech watchers should care

Tone: editorial, authoritative, engaging. Not promotional. Not a press release. Write like a technology journalist. No markdown, no headers, just flowing paragraphs."""

HOOD_PROMPT = """You are the technical editor of GitWire, a weekly GitHub publication. Write a technical breakdown of this repository for experienced developers.

Repository: {full_name}
Description: {description}
Stars: {stars}
Language: {language}
Topics: {topics}
URL: {url}

Write 2 paragraphs (150-180 words) covering:
- What the architecture or technical approach is interesting about this repo
- What specific problem it solves at a code level and why the implementation approach stands out

Tone: technical, precise, written for developers. Assume the reader codes. No markdown, no headers, flowing paragraphs."""

IDEA_PROMPT = """You are the product and ideas editor of GitWire, a weekly GitHub publication. Your readers include founders, product managers, and tech-curious non-developers.

Repository: {full_name}
Description: {description}
Stars: {stars}
Language: {language}
Topics: {topics}
URL: {url}

Write 2 paragraphs (150-180 words) covering:
- What is the core idea here, stripped of all the code — what is this really doing?
- What market gap or human need does this address? Who would want this as a product?

Tone: accessible, insightful, no jargon. Write for someone smart who doesn't necessarily code. No markdown, no headers, flowing paragraphs."""

DROPS_PROMPT = """You are a writer for GitWire, a weekly GitHub publication. Write ultra-short descriptions for these GitHub repositories — one sentence each, max 20 words, written for a mixed technical/non-technical audience. Make each one feel like a punchy magazine blurb.

{repos_list}

Return ONLY a JSON array of strings, one per repo, in the same order. No markdown, no explanation, just the raw JSON array."""

RESURRECTION_PROMPT = """You are the curator of GitWire's "Resurrection" section — a weekly pick of an older repository that has suddenly resurfaced and is gaining renewed attention.

Repository: {full_name}
Description: {description}
Stars: {stars}
Language: {language}
Created: {created_at}
Last pushed: {pushed_at}
URL: {url}

Write 2 paragraphs (120-150 words):
- What this repo is and why it originally mattered
- Why it might be resurfacing now — what changed in the ecosystem that makes this relevant again?

Tone: curious, editorial. No markdown, no headers, flowing paragraphs."""


def repo_prompt_vars(r):
    return {
        "full_name":   r["full_name"],
        "description": r["description"] or "No description",
        "stars":       r["stargazers_count"],
        "language":    r["language"] or "Unknown",
        "topics":      ", ".join(r["topics"]) or "none",
        "url":         r["html_url"],
        "created_at":  r.get("created_at", "")[:10],
        "pushed_at":   r.get("pushed_at",  "")[:10],
    }


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("── GitWire Engine ──────────────────────────────")
    print(f"Edition {edition_number()} · {week_range()}")
    print()

    # 1. Fetch trending repos
    print("→ Fetching trending repos from GitHub…")
    trending = fetch_trending_repos(days_ago=7, per_page=25)
    if not trending:
        raise RuntimeError("No repositories returned from GitHub Search API.")
    print(f"  Found {len(trending)} repos. Lead: {trending[0]['full_name']}")
    time.sleep(1)

    # 2. Editorial picks — same indices as generateEdition()
    lead       = trending[0]
    fresh_drops = trending[1:7]
    idea_repo  = trending[math.floor(len(trending) * 0.3)] or trending[1]
    hood_repo  = trending[math.floor(len(trending) * 0.2)] or trending[2]

    # 3. Resurrection
    print("→ Fetching resurrection candidate…")
    resurrection = fetch_resurrection_repo()
    print(f"  Resurrection: {resurrection['full_name'] if resurrection else 'none found'}")
    time.sleep(2)

    # 4. Gemini — Signal
    print(f"→ Writing Signal article ({lead['full_name']})…")
    signal_article = call_gemini(SIGNAL_PROMPT.format(**repo_prompt_vars(lead)))
    time.sleep(2)

    # 5. Gemini — Under the Hood
    print(f"→ Writing Under the Hood ({hood_repo['full_name']})…")
    hood_article = call_gemini(HOOD_PROMPT.format(**repo_prompt_vars(hood_repo)))
    time.sleep(2)

    # 6. Gemini — The Idea
    print(f"→ Writing The Idea ({idea_repo['full_name']})…")
    idea_article = call_gemini(IDEA_PROMPT.format(**repo_prompt_vars(idea_repo)))
    time.sleep(2)

    # 7. Gemini — Fresh Drops (one call for all 6)
    print("→ Writing Fresh Drops descriptions…")
    repos_list = "\n".join(
        f"{i+1}. {r['full_name']}: {r['description'] or 'No description'} "
        f"({r['language'] or '?'}, {r['stargazers_count']} stars)"
        for i, r in enumerate(fresh_drops)
    )
    drops_raw = call_gemini(DROPS_PROMPT.format(repos_list=repos_list))
    try:
        drop_descriptions = json.loads(drops_raw.replace("```json", "").replace("```", "").strip())
    except Exception:
        drop_descriptions = [r["description"] or "A new repository worth watching." for r in fresh_drops]
    time.sleep(2)

    # 8. Gemini — Resurrection
    resurrection_article = ""
    if resurrection:
        print(f"→ Writing Resurrection article ({resurrection['full_name']})…")
        resurrection_article = call_gemini(RESURRECTION_PROMPT.format(**repo_prompt_vars(resurrection)))
        time.sleep(2)

    # 9. By the numbers
    print("→ Computing statistics…")
    total_stars = sum(r["stargazers_count"] for r in trending)
    lang_counts = {}
    for r in trending:
        if r.get("language"):
            lang_counts[r["language"]] = lang_counts.get(r["language"], 0) + 1
    top_lang   = sorted(lang_counts, key=lang_counts.get, reverse=True)[0] if lang_counts else "—"
    avg_stars  = round(total_stars / len(trending))
    most_forked = sorted(trending, key=lambda r: r.get("forks_count", 0), reverse=True)[0]

    # 10. Assemble output — shape must match renderEdition(data) exactly
    output = {
        "edition":     edition_number(),
        "weekRange":   week_range(),
        "generatedAt": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),

        # Repo objects (slimmed)
        "lead":        slim_repo(lead),
        "hoodRepo":    slim_repo(hood_repo),
        "ideaRepo":    slim_repo(idea_repo),
        "freshDrops":  [slim_repo(r) for r in fresh_drops],
        "resurrection": slim_repo(resurrection) if resurrection else None,

        # Editorial copy
        "signalArticle":       signal_article,
        "hoodArticle":         hood_article,
        "ideaArticle":         idea_article,
        "dropDescriptions":    drop_descriptions,
        "resurrectionArticle": resurrection_article,

        # Stats — numbers.mostForked must be a slim repo object (used in renderEdition)
        "numbers": {
            "repoCount":  len(trending),
            "totalStars": total_stars,
            "avgStars":   avg_stars,
            "topLang":    top_lang,
            "mostForked": slim_repo(most_forked),
        },
    }

    # 11. Write
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print(f"✓ Written → {OUTPUT_FILE}")
    print(f"  Edition {output['edition']} · {output['weekRange']}")
    print(f"  Lead: {output['lead']['full_name']} ({output['lead']['stargazers_count']} ★)")
    print(f"  Generated at: {output['generatedAt']}")


if __name__ == "__main__":
    main()
