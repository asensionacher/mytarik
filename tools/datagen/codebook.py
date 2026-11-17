"""Catálogo de códigos y descripciones para el corpus sintético.

Fuentes (todas oficiales y ya presentes en el equipo):

* ``/home/seby/taric/<mes>/Nomenclature EN.xlsx`` — export de la nomenclatura
  TARIC (25.878 filas, EN, niveles 2/4/6/8/10).
* ``/home/seby/taric/<mes>/.../Declarable codes.xlsx`` — códigos declarables
  (columna ``IS_LEAF``); define qué códigos de 10 dígitos existen de verdad.
* ``data/real/ebti_labels.jsonl`` — 123.458 resoluciones EBTI públicas. De ahí
  salen descripciones de producto reales en español (4.476) y en inglés (1.018).

El catálogo resultante tiene una entrada por CN8 con:

    cn8, hs6, chapter, desc_en, desc_es, taric10 (lista de hijos declarables),
    source_es ("ebti" | "cn")

Se cachea en ``.cache/codebook.json`` para que la generación sea reproducible y
no dependa de leer 25.878 filas cada vez.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import openpyxl
from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0

ROOT = Path("/home/seby/mytarik")
DATAGEN = ROOT / "tools" / "datagen"
CACHE = DATAGEN / ".cache"
TARIC_MONTHS = ("2026-11", "2026-10")


def _find_taric_file(name: str) -> Path:
    for month in TARIC_MONTHS:
        direct = ROOT.parent / "taric" / month / name
        if direct.is_file():
            return direct
        found = sorted((ROOT.parent / "taric" / month).rglob(name))
        if found:
            return found[0]
    raise FileNotFoundError(f"no se encuentra {name} en /home/seby/taric")


def _read_rows(path: Path) -> list[tuple]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    return [dict(zip(header, row)) for row in rows[1:]]


def _digits(value: object) -> str:
    """Código del export CIRCABC: «6205200000 80» -> «6205200000»."""
    text = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 7:
        digits = digits.zfill(8)
    elif len(digits) == 9:
        digits = digits.zfill(10)
    return digits


def _clean_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("|", " ").replace("–", "-")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" .;:")
    return text


@dataclass
class CodeEntry:
    cn8: str
    hs6: str
    chapter: str
    desc_en: str
    desc_en_ebti: str | None
    desc_es: str | None
    taric10: list[str]
    source_es: str
    segments: list[str]


_ACRONYM_RE = re.compile(r"^[A-Z0-9][A-Z0-9&./-]{1,}$")


def _join_segments(segments: list[str]) -> str:
    """Une la jerarquía en una frase legible («Shirts, of cotton»)."""
    parts: list[str] = []
    for seg in segments:
        seg = _clean_text(seg)
        if not seg:
            continue
        if parts and not _ACRONYM_RE.match(seg.split()[0]):
            seg = seg[0].lower() + seg[1:]
        parts.append(seg)
    text = ", ".join(parts)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = text.replace(", ,", ",")
    if text:
        text = text[0].upper() + text[1:]
    return text


def _nomenclature(max_rows: int = 0) -> dict[str, dict]:
    """Devuelve {cn8: {"desc": str, "taric": [codes]}} desde la nomenclatura."""
    path = _find_taric_file("Nomenclature EN.xlsx")
    rows = _read_rows(path)

    stack: list[tuple[int, str]] = []  # (profundidad, texto)
    heading = ""
    cn8_segments: dict[str, list[str]] = {}  # cn8 -> cadena más profunda vista
    cn8_leaf: dict[str, list[str]] = {}

    for row in rows:
        code = _digits(row.get("goods code"))
        if len(code) != 10:
            continue
        hier = row.get("hier. pos.") or 0
        indent_raw = row.get("indent")
        depth = str(indent_raw).count("-") if indent_raw else 0
        text = _clean_text(row.get("description"))
        if not text:
            continue

        if hier == 2:  # capítulo: reinicia
            stack = []
            heading = ""
            continue
        if hier == 4:  # partida
            stack = []
            heading = text
            continue

        while stack and stack[-1][0] >= depth:
            stack.pop()
        chain = ([heading] if heading else []) + [t for _, t in stack] + [text]
        cn8 = code[:8]
        segs = [s for s in (_clean_text(c) for c in chain) if s]
        if code.endswith("00"):
            cn8_segments[cn8] = segs  # la fila CN8 pisa a las anteriores
        else:
            cn8_segments.setdefault(cn8, segs)
            cn8_leaf.setdefault(cn8, []).append(code)
        stack.append((depth, text))

    return {
        cn8: {"segments": segs, "desc": _join_segments(segs), "taric": sorted(set(cn8_leaf.get(cn8, [])))}
        for cn8, segs in cn8_segments.items()
    }


def _declarable() -> set[str]:
    path = _find_taric_file("Declarable codes.xlsx")
    rows = _read_rows(path)
    leaves = set()
    for row in rows:
        if str(row.get("is_leaf") or "").strip() != "1":
            continue
        code = _digits(row.get("goods code"))
        if len(code) == 10:
            leaves.add(code)
    return leaves


_ES_STOP = {"de", "del", "la", "el", "los", "las", "un", "una", "y", "o", "para",
            "con", "en", "por", "que", "se", "su", "sus", "al", "lo", "como"}
_EN_STOP = {"the", "of", "for", "with", "and", "a", "an", "in", "to", "from", "is",
            "presented", "put", "up"}


def _looks_spanish(text: str) -> bool:
    words = re.findall(r"[a-záéíóúñü]+", text.lower())
    if not words:
        return False
    hits = sum(1 for w in words if w in _ES_STOP)
    return hits >= 2 and not any(w in _EN_STOP for w in words[:2])


def _looks_english(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    return sum(1 for w in words if w in _EN_STOP) >= 2 and not re.search(r"[áéíóúñ]", text)


def _ebti_descriptions() -> tuple[dict[str, str], dict[str, str]]:
    """Devuelve ({cn8: descripción ES}, {cn8: descripción EN}) a partir de EBTI.

    El campo ``language`` del JSONL no es fiable (hay textos en sueco dentro de
    ``en``), así que se detecta el idioma del texto. Solo se aceptan frases que
    empiecen por mayúscula y tengan entre 12 y 160 caracteres.
    """
    es: dict[str, str] = {}
    en: dict[str, str] = {}
    path = ROOT / "data" / "real" / "ebti_labels.jsonl"
    scanned = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # El campo language filtra 95 % del trabajo: langdetect sobre 123k
            # frases tarda minutos y solo interesan las candidatas es/en.
            if row.get("language") not in ("es", "en"):
                continue
            scanned += 1
            cn8 = str(row.get("cn8") or "")
            desc = _clean_text(row.get("description"))
            if len(cn8) != 8 or not desc:
                continue
            head = re.split(r"(?<=[.;:])\s+", desc, maxsplit=1)[0].strip()
            if not (12 <= len(head) <= 160) or not head[:1].isupper():
                continue
            if re.search(r"\d{6,}", head) or head.endswith(":"):
                continue
            if re.match(r"(?i)^(descripci[oó]n|datos|informaci[oó]n|producto)\b", head):
                continue
            if len(re.findall(r"\w+", head)) < 3:
                continue
            try:
                lang = detect(head)
            except Exception:
                continue
            if lang == "es" and " " in head:
                current = es.get(cn8)
                if current is None or len(head) < len(current):
                    es[cn8] = head
            elif lang == "en" and " " in head:
                current = en.get(cn8)
                if current is None or len(head) < len(current):
                    en[cn8] = head
    print(f"  EBTI: {scanned} frases es/en revisadas")
    return es, en


def _strip_fragments(text: str) -> str:
    text = re.sub(r"\b(?:kg|g)\b\.?\s*$", "", text).strip(" ,;.")
    return text


def build_codebook(force: bool = False) -> list[CodeEntry]:
    out = CACHE / "codebook.json"
    if out.is_file() and not force:
        return [CodeEntry(**row) for row in json.loads(out.read_text(encoding="utf-8"))]

    nom = _nomenclature()
    leaves = _declarable()
    es, en = _ebti_descriptions()

    entries: list[CodeEntry] = []
    for cn8, item in nom.items():
        segments = item["segments"]
        desc_en = _strip_fragments(item["desc"])
        if len(desc_en) < 6:
            continue
        taric = [t for t in item["taric"] if t in leaves] or ([cn8 + "00"] if cn8 + "00" in leaves else [])
        if not taric:
            continue
        desc_es = es.get(cn8)
        desc_en_ebti = en.get(cn8)
        source = "ebti_es" if desc_es else ("ebti_en" if desc_en_ebti else "cn")
        entries.append(
            CodeEntry(
                cn8=cn8,
                hs6=cn8[:6],
                chapter=cn8[:2],
                desc_en=desc_en,
                desc_en_ebti=desc_en_ebti,
                desc_es=desc_es,
                taric10=taric,
                source_es=source,
                segments=segments,
            )
        )
    entries.sort(key=lambda e: e.cn8)
    CACHE.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=1), encoding="utf-8")
    return entries


if __name__ == "__main__":
    entries = build_codebook(force=True)
    print(f"CN8 con TARIC10 declarable: {len(entries)}")
    for chapter in ("03", "22", "33", "39", "42", "48", "61", "62", "64", "69", "73", "84", "85", "87", "90", "94", "95"):
        sample = [e for e in entries if e.chapter == chapter][:3]
        print(f"\n=== capítulo {chapter}  ({sum(1 for e in entries if e.chapter == chapter)} códigos)")
        for e in sample:
            print(f"  {e.cn8} | {e.desc_en[:88]}")
            if e.desc_es:
                print(f"          ES [{e.source_es}]: {e.desc_es[:88]}")
    es_count = sum(1 for e in entries if e.source_es == "ebti_es")
    print(f"\nCon descripción ES real (EBTI): {es_count}")
