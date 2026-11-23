#!/usr/bin/env python3
"""Collect web evidence for provisional TARIC labels.

The evidence is advisory. It never approves a term by itself.
Providers: DuckDuckGo HTML by default; Google/Bing can be added with API keys.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, time, urllib.parse, urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
TRUSTED = ("eur-lex.europa.eu", "boe.es", "eservices.minfin.fgov.be", "taxation-customs.ec.europa.eu", "ec.europa.eu", "thetradehub.eu", "tariffnumber.com")
CODE_RE = re.compile(r"\b(\d{8,10})\b")


def ddg(query: str) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        html = response.read().decode("utf-8", "replace")
    results = []
    for block in re.findall(r'<div[^>]+class="result[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S)[:8]:
        m = re.search(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        s = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        link = unescape(m.group(1))
        if "uddg=" in link:
            link = urllib.parse.unquote(re.search(r"uddg=([^&]+)", link).group(1))
        title = re.sub(r"<[^>]+>", " ", unescape(m.group(2)))
        snippet = re.sub(r"<[^>]+>", " ", unescape(s.group(1))) if s else ""
        results.append({"url": link, "title": " ".join(title.split()), "snippet": " ".join(snippet.split())})
    return results


def brave(query: str) -> list[dict]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is not set")
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "count": 10})
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": key,
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    results = []
    for item in (data.get("web", {}).get("results") or [])[:10]:
        results.append({
            "url": item.get("url", ""),
            "title": " ".join(str(item.get("title", "")).split()),
            "snippet": " ".join(str(item.get("description", "")).split()),
        })
    return results


def verdict(proposed: str, results: list[dict], known: set[str]) -> tuple[str, str | None, str | None]:
    for result in results:
        text = f"{result['title']} {result['snippet']} {result['url']}"
        codes = [c.zfill(10) for c in CODE_RE.findall(text) if c.zfill(10) in known]
        if proposed in codes:
            domain = urllib.parse.urlparse(result["url"]).netloc
            return ("corroborated" if any(d in domain for d in TRUSTED) else "weak_match", proposed, result["url"])
        if codes:
            return "contradicted", codes[0], result["url"]
    return "unknown", None, results[0]["url"] if results else None


def main():
    env_path = Path(".env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/termbase.sqlite")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--provider", choices=("duckduckgo", "brave"), default="duckduckgo")
    args = ap.parse_args()
    if args.provider == "brave" and not os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
        print("BRAVE_SEARCH_API_KEY is not set; no queries were made.")
        return 2
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.executescript("""CREATE TABLE IF NOT EXISTS web_evidence(
      id INTEGER PRIMARY KEY AUTOINCREMENT, term_id INTEGER, term TEXT, proposed_code TEXT,
      found_code TEXT, provider TEXT, query TEXT, url TEXT, verdict TEXT, fetched_at TEXT);""")
    known = {r[0] for r in db.execute("SELECT code FROM taric_codes")}
    rows = db.execute("""SELECT t.id,t.term,tc.code FROM commercial_terms t JOIN term_code tc ON tc.term_id=t.id
      WHERE t.source='llm_code' AND t.status='provisional' AND t.review_status='unreviewed'
      AND NOT EXISTS (SELECT 1 FROM web_evidence w WHERE w.term_id=t.id AND w.proposed_code=tc.code)
      ORDER BY RANDOM() LIMIT ?""", (args.limit,)).fetchall()
    counts = {"corroborated": 0, "weak_match": 0, "contradicted": 0, "unknown": 0}
    for row in rows:
        query = f'"{row["term"]}" TARIC codigo arancelario'
        try:
            results = brave(query) if args.provider == "brave" else ddg(query)
        except Exception as exc:
            print("search error", exc, flush=True)
            results = []
        v, found, url = verdict(row["code"], results, known)
        counts[v] = counts.get(v, 0) + 1
        db.execute("INSERT INTO web_evidence(term_id,term,proposed_code,found_code,provider,query,url,verdict,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (row["id"], row["term"], row["code"], found, args.provider, query, url, v, datetime.now().isoformat(timespec="seconds")))
        db.commit()
        print(f"{v:12s} {row['term'][:55]:55s} proposed={row['code']} found={found}", flush=True)
        time.sleep(args.delay)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    db.close()


if __name__ == "__main__":
    raise SystemExit(main())
