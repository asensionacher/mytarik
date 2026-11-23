#!/usr/bin/env python3
"""Re-evaluate already-fetched web evidence by reading the result pages.

This does not call the search API again. It only fetches the URLs Brave
already returned and looks for the proposed code in the full page.
"""
from __future__ import annotations
import re
import sqlite3
import urllib.parse
import urllib.request
from html import unescape

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
TRUSTED = ("eur-lex.europa.eu", "boe.es", "eservices.minfin.fgov.be", "taxation-customs.ec.europa.eu", "ec.europa.eu", "thetradehub.eu", "tariffnumber.com", "taricsupport.com")
CODE_RE = re.compile(r"\b(\d{8,10})\b")


def page_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read(700_000).decode("utf-8", "replace")
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return " ".join(unescape(raw).split())


def main() -> int:
    db = sqlite3.connect("data/termbase.sqlite")
    db.row_factory = sqlite3.Row
    known = {row[0] for row in db.execute("SELECT code FROM taric_codes")}
    rows = db.execute("""SELECT id,term,proposed_code,url,verdict FROM web_evidence
        WHERE provider='brave' AND url IS NOT NULL AND url != ''""").fetchall()
    counts = {"corroborated": 0, "weak_match": 0, "contradicted": 0, "unknown": 0}
    for row in rows:
        try:
            text = page_text(row["url"])
        except Exception as exc:
            print(f"fetch error {row['id']}: {exc}", flush=True)
            continue
        codes = [c.zfill(10) for c in CODE_RE.findall(text) if c.zfill(10) in known]
        proposed = row["proposed_code"]
        domain = urllib.parse.urlparse(row["url"]).netloc
        if proposed in codes:
            verdict = "corroborated" if any(d in domain for d in TRUSTED) else "weak_match"
            found = proposed
        elif codes:
            verdict, found = "contradicted", codes[0]
        else:
            verdict, found = "unknown", None
        counts[verdict] += 1
        db.execute("UPDATE web_evidence SET found_code=?, verdict=? WHERE id=?", (found, verdict, row["id"]))
        db.commit()
        print(f"{verdict:12s} {row['term'][:50]:50s} proposed={proposed} found={found}", flush=True)
    print(counts)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
