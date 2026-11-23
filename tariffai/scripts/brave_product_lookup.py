#!/usr/bin/env python3
"""Query Brave for commercial product names and show candidate TARIC codes."""
import json, os, re, urllib.parse, urllib.request
from pathlib import Path

TERMS = [
    "bobina de aluminio", "tornillos de acero", "botella de plástico",
    "cepillo de dientes", "cargador de móvil", "altavoz Bluetooth",
    "nevera", "lavadora", "gafas de sol", "pelota de fútbol",
]
CODE_RE = re.compile(r"\b(\d{8,10})\b")


def load_env():
    p = Path(".env")
    if p.is_file():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def search(term):
    key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY missing")
    q = f'"{term}" TARIC codigo arancelario'
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": q, "count": 8})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode())
    out = []
    for x in (data.get("web", {}).get("results") or []):
        text = " ".join([str(x.get("title", "")), str(x.get("description", "")), str(x.get("url", ""))])
        out.append({"title": x.get("title"), "url": x.get("url"), "codes": sorted(set(CODE_RE.findall(text)))})
    return out


load_env()
for term in TERMS:
    print("\n===", term)
    try:
        for result in search(term)[:5]:
            print(result["codes"], result["title"][:80], result["url"][:120])
    except Exception as exc:
        print("ERROR", exc)
