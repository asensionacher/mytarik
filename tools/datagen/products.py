"""Líneas de factura verosímiles a partir del catálogo real de códigos.

La descripción impresa sale siempre de una descripción real (EBTI o nomenclatura
oficial) y se le añaden datos comerciales neutros: marca, referencia, color,
talla, formato de embalaje, lote. Nunca se añade un dato que pueda cambiar la
clasificación (composición, pureza, uso, forma de presentación distinta).
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

import parties

# Capítulos que se usan en el corpus, con su peso relativo.
CHAPTER_WEIGHTS = {
    "61": 9, "62": 9, "63": 7, "64": 5, "39": 6, "42": 4, "48": 3, "49": 2,
    "69": 4, "70": 3, "73": 7, "76": 3, "82": 3, "83": 3, "84": 10, "85": 10,
    "87": 6, "90": 5, "94": 5, "95": 5, "96": 2, "40": 4, "44": 3, "68": 2,
    "03": 4, "07": 3, "08": 3, "09": 2, "10": 2, "16": 3, "17": 2, "19": 3,
    "20": 4, "21": 3, "22": 4, "33": 3, "34": 2, "38": 2, "91": 1,
}

ARCHETYPE_CHAPTERS = {
    "EXTRA_EU": ["61", "62", "63", "64", "39", "42", "69", "73", "76", "82", "83",
                 "84", "85", "87", "90", "94", "95", "03", "16", "20", "21", "96", "40"],
    "INTRA_EU": ["84", "85", "87", "39", "48", "69", "70", "73", "94", "61", "62",
                 "20", "22", "33", "90", "44", "83"],
    "DOMESTIC": ["39", "48", "73", "76", "82", "84", "85", "87", "94", "20", "21",
                 "22", "17", "19", "63", "96"],
}

# Descripciones que no queremos en una factura de mercancías corrientes.
_EXCLUDE_RE = re.compile(
    r"(?i)\b(nuclear|arms|munitions|works of art|collectors|antiques|waste and scrap|"
    r"tobacco|human blood|pharmaceutical|contraceptive|organs|explosive|coin|"
    r"unmanufactured|in bulk|live (?:horses|cattle|swine|sheep|goats|poultry))|"
    r"(motor vehicles for the transport|passenger cars|vehicles for the transport of goods|"
    r"special purpose motor vehicles|chassis fitted with engines|road tractors)",
)

_UNIT_BY_CHAPTER = {
    "61": ("PCS", "UNITS"), "62": ("PCS", "UNITS"),
    "63": ("PCS", "SETS", "PAIRS"), "64": ("PAIRS", "PCS"),
    "03": ("KG", "CTN"), "07": ("KG", "CTN"), "08": ("KG", "CTN"), "09": ("KG", "CTN"),
    "10": ("KG", "BAG"), "16": ("KG", "CTN"), "17": ("KG", "CTN"), "19": ("KG", "CTN"),
    "20": ("KG", "CTN"), "21": ("KG", "CTN"), "22": ("BTL", "L", "CTN"),
    "33": ("PCS", "SETS"), "34": ("PCS", "KG"),
    "39": ("PCS", "KG", "ROLL"), "40": ("PCS", "KG"), "44": ("PCS", "M3"),
    "48": ("PCS", "KG", "ROLL"), "49": ("PCS", "KG"), "68": ("PCS", "SET"),
    "69": ("PCS", "SET"), "70": ("PCS", "SET"), "73": ("PCS", "KG", "SET"),
    "76": ("PCS", "KG"), "82": ("PCS", "SET"), "83": ("PCS", "SET", "PAIRS"),
    "84": ("PCS", "SET", "UNITS"), "85": ("PCS", "SET", "UNITS"), "87": ("PCS", "SET"),
    "90": ("PCS", "SET", "UNITS"), "91": ("PCS", "SET"), "94": ("PCS", "SET"),
    "95": ("PCS", "SET"), "96": ("PCS", "SET", "KG"),
}

# Precio unitario de referencia en EUR y peso neto por unidad (kg).
_PRICE_BY_CHAPTER = {
    "61": (4, 42), "62": (6, 65), "63": (3, 45), "64": (8, 70), "39": (0.4, 30),
    "42": (5, 90), "48": (0.5, 12), "49": (0.4, 9), "68": (2, 40), "69": (2, 25),
    "70": (1, 30), "73": (0.8, 45), "76": (1.2, 55), "82": (1.5, 40), "83": (1, 35),
    "84": (15, 900), "85": (8, 600), "87": (4, 350), "90": (10, 500), "91": (0.8, 20),
    "94": (12, 400), "95": (2, 60), "96": (0.5, 18), "40": (0.5, 25), "44": (2, 80),
    "03": (3, 18), "07": (0.6, 6), "08": (0.8, 6), "09": (1.5, 18), "10": (0.5, 3),
    "16": (1.5, 14), "17": (0.8, 5), "19": (1, 9), "20": (0.7, 8), "21": (1.2, 15),
    "22": (0.9, 40), "33": (1.5, 45), "34": (0.5, 15), "38": (1.5, 30),
}

# Valor orientativo en EUR por kg. Se usa para que el peso sea coherente con el
# precio: una máquina de 5.000 EUR no puede pesar 300 g.
_EUR_PER_KG = {
    "03": 6, "07": 2, "08": 2, "09": 4, "10": 1, "16": 4, "17": 2, "19": 3,
    "20": 2.5, "21": 4, "22": 2.5, "33": 45, "34": 22, "38": 8, "39": 4, "40": 3,
    "42": 30, "44": 3, "48": 2.5, "49": 2, "61": 55, "62": 55, "63": 30, "64": 35,
    "68": 4, "69": 6, "70": 10, "73": 3, "76": 6, "82": 6, "83": 8, "84": 55,
    "85": 90, "87": 12, "90": 160, "91": 220, "94": 16, "95": 28, "96": 8,
}

_COLORS_ES = ["NEGRO", "AZUL MARINO", "BLANCO", "GRIS", "BEIG", "VERDE OLIVA",
              "BURDEOS", "CAMEL", "ROJO", "ANTRACITA"]
_COLORS_EN = ["BLACK", "NAVY", "WHITE", "GREY", "BEIGE", "OLIVE", "BURGUNDY",
              "CAMEL", "RED", "CHARCOAL"]
_TEXTILE_SIZES = ["S-XL", "XS-L", "M-XXL", "36-46", "38-48", "ONE SIZE"]
_SHOE_SIZES = ["36-41", "38-43", "40-45", "41-46"]

# Caracteres fuera de Latin-1 rompen las fuentes base de reportlab. Se
# sustituyen aquí para que el texto impreso sea exactamente el del ground truth.
_TRANSLIT = str.maketrans({
    "\u2264": "<=", "\u2265": ">=", "\u00d7": "x", "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...",
    "\u00b7": ".", "\u00a0": " ", "\u2032": "'", "\u2033": '"', "\u2212": "-",
})


def printable(text: str) -> str:
    for source, target in (("CM$3", "CM3"), ("CM$2", "CM2"), ("M$3", "M3"),
                           ("M$2", "M2"), ("$3", "3"), ("$2", "2"), ("$", " ")):
        text = text.replace(source, target)
    text = text.translate(_TRANSLIT)
    text = "".join(ch if 32 <= ord(ch) < 256 else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip(" ,;.")


@dataclass
class Catalog:
    entries: list
    by_chapter: dict[str, list]
    by_cn8: dict[str, object]

    @classmethod
    def load(cls, entries: list) -> "Catalog":
        by_chapter: dict[str, list] = {}
        for entry in entries:
            by_chapter.setdefault(entry.chapter, []).append(entry)
        return cls(entries, by_chapter, {e.cn8: e for e in entries})


def _clean_base(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .;,")
    text = re.sub(r"\b(?:kg|g)\b$", "", text).strip(" ,;.")
    return printable(text)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;.-")


def _shorten(segments: list[str], limit: int = 105) -> str:
    full = parties_segments_join(segments)
    if len(full) <= limit:
        return full
    head = _cut(segments[0], 55) if segments else ""
    tail = [s for s in segments[1:] if s][-2:]
    text = parties_segments_join([head] + tail)
    if len(text) > limit:
        text = parties_segments_join([head] + tail[-1:])
    if len(text) > limit:
        text = _cut(text, limit)
    return text


def parties_segments_join(segments: list[str]) -> str:
    from codebook import _join_segments

    return _join_segments(segments)


def _usable(entry) -> bool:
    text = entry.desc_en
    if len(text) < 8 or _EXCLUDE_RE.search(text):
        return False
    # «Other» a secas no describe nada.
    if re.fullmatch(r"(?i)other[ .,]*", entry.desc_en_ebti or entry.desc_en or ""):
        return False
    return True


def _base_description(entry, lang: str) -> str:
    if lang == "es" and entry.desc_es:
        return _clean_base(entry.desc_es)
    if lang == "en" and entry.desc_en_ebti:
        return _clean_base(entry.desc_en_ebti)
    return _shorten(entry.segments)


def _modifier_bits(rng: random.Random, entry, archetype: str, lang: str) -> tuple[list[str], str]:
    """Datos comerciales neutros. Devuelve (fragmentos, tipo de producto)."""
    chapter = entry.chapter
    bits: list[str] = []
    kind = "general"

    if rng.random() < 0.55:
        bits.append(rng.choice(parties.BRANDS))

    if chapter in {"61", "62", "63"}:
        kind = "textile"
        if rng.random() < 0.7:
            bits.append(rng.choice(_COLORS_ES if lang == "es" else _COLORS_EN))
        if rng.random() < 0.6:
            bits.append(f"TALLAS {rng.choice(_TEXTILE_SIZES)}" if lang == "es" else f"SIZES {rng.choice(_TEXTILE_SIZES)}")
        if rng.random() < 0.75:
            bits.append(f"{rng.choice((12, 24, 36, 48))} PCS/CTN")
    elif chapter == "64":
        kind = "footwear"
        if rng.random() < 0.6:
            bits.append(f"TALLAS {rng.choice(_SHOE_SIZES)}" if lang == "es" else f"SIZES {rng.choice(_SHOE_SIZES)}")
        if rng.random() < 0.6:
            bits.append(f"{rng.choice((6, 10, 12))} PAIRS/CTN")
    elif chapter == "22":
        kind = "beverage"
        if rng.random() < 0.75:
            bits.append(f"{rng.choice((6, 12, 24))} x {rng.choice((70, 75))} CL")
        bits.append(f"LOTE L{rng.randint(1000, 9999)}")
        if rng.random() < 0.4:
            bits.append(f"BEST BEFORE {rng.randint(1, 12):02d}/2029" if lang == "en" else f"CONSUMIR PREF. {rng.randint(1, 12):02d}/2029")
    elif chapter in {"03", "07", "08", "09", "10", "16", "17", "19", "20", "21"}:
        kind = "food"
        if rng.random() < 0.7:
            grams = rng.choice((200, 250, 400, 500, 1000, 5))
            if grams == 5:
                bits.append(f"{rng.choice((4, 6, 12))} x 5 KG")
            elif grams < 1000:
                bits.append(f"{rng.choice((6, 12, 24))} x {grams} G")
            else:
                bits.append(f"{rng.choice((4, 6, 12))} x 1 KG")
        bits.append(f"LOTE L{rng.randint(1000, 9999)}")
        if rng.random() < 0.5:
            bits.append(f"BEST BEFORE {rng.randint(1, 12):02d}/2028" if lang == "en" else f"CONSUMIR PREF. {rng.randint(1, 12):02d}/2028")
    elif chapter in {"84", "85", "90"}:
        kind = "tech"
        if rng.random() < 0.75:
            bits.append(f"MODEL {rng.choice(('AX','BX','CX','DX','HX','MX'))}-{rng.randint(100, 9999)}")
        if chapter == "85" and rng.random() < 0.5:
            bits.append(rng.choice(("230 V / 50 Hz", "110-240 V", "12 V DC")))
    elif chapter == "87":
        kind = "auto"
        if rng.random() < 0.7:
            bits.append(f"OEM {rng.choice(('A','B','C','D'))}{rng.randint(10000, 99999)}")
    elif chapter == "94":
        kind = "furniture"
        if rng.random() < 0.6:
            bits.append(f"{rng.randint(60, 220)} x {rng.randint(40, 120)} CM")
        if rng.random() < 0.5:
            bits.append(rng.choice(_COLORS_ES if lang == "es" else _COLORS_EN))
    elif chapter == "95":
        kind = "toy"
        if rng.random() < 0.5:
            bits.append(f"AGE {rng.randint(3, 12)}+")
        if rng.random() < 0.4:
            bits.append(f"{rng.choice((24, 48, 96))} PCS/CTN")
    elif chapter in {"39", "40", "42", "48", "70", "73", "76", "82", "83", "96"}:
        kind = "hardware"
        if rng.random() < 0.5:
            bits.append(f"{rng.choice((10, 20, 25, 50))} PCS/BOX")
    elif chapter in {"33", "34", "38"}:
        kind = "cosmetic"
        if rng.random() < 0.6:
            bits.append(f"{rng.choice((50, 100, 200, 400))} ML")
        bits.append(f"LOTE L{rng.randint(100, 999)}")

    if rng.random() < 0.6:
        prefix = "REF." if lang == "es" else "REF."
        bits.append(f"{prefix} {rng.choice(('NV','TS','HD','QL','RM','ZK'))}{rng.randint(1000, 9999)}")

    if archetype == "INTRA_EU" and chapter in {"84", "85", "87", "90"} and rng.random() < 0.4:
        bits.append("CE" if lang == "es" else "CE MARKED")

    return bits, kind


_DANGLING = re.compile(
    r"(?i)(?:,?\s*\b(?:ref|sizes|tallas|lote|model|oem|age|best|consumir|ce|pcs|box|ml))\.?$"
)


def _fit(text: str, limit: int = 118) -> str:
    if len(text) <= limit:
        return text
    parts = text.split(", ")
    while len(parts) > 1 and len(", ".join(parts)) > limit:
        parts.pop()
    text = ", ".join(parts)
    if len(text) > limit:
        text = _cut(text, limit)
        text = _DANGLING.sub("", text).strip(" ,;.-")
    return text


def _format_description(base: str, bits: list[str], lang: str, uppercase: bool) -> str:
    text = base
    if bits:
        text = f"{text}, " + ", ".join(bits)
    text = re.sub(r"\s+", " ", text).strip(" ,;.")
    text = _fit(text, 118)
    if uppercase:
        text = text.upper()
    return printable(text)


@dataclass
class Line:
    line_no: int
    description: str
    cn8: str
    hs6: str
    taric10: str
    origin: str
    quantity: float
    unit: str
    unit_price: float
    amount: float
    net_weight: float
    gross_weight: float
    packages: int
    kind: str = "general"

    def as_dict(self) -> dict:
        return {
            "line_no": self.line_no,
            "description": self.description,
            "cn8": self.cn8,
            "hs6": self.hs6,
            "taric10": self.taric10,
            "origin": self.origin,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "net_weight_kg": round(self.net_weight, 2),
            "gross_weight_kg": round(self.gross_weight, 2),
            "packages": self.packages,
        }


def _price_range(chapter: str, archetype: str) -> tuple[float, float]:
    low, high = _PRICE_BY_CHAPTER.get(chapter, (1, 50))
    if archetype == "INTRA_EU":
        low, high = low * 1.1, high * 1.2
    return low, high


def _quantity_for(unit: str, price_eur: float, rng: random.Random) -> float:
    """Cantidad coherente con el precio: lo caro se compra en pocas unidades."""
    target = 10 ** rng.uniform(2.3, 4.35)  # 200 .. 22.000 EUR por línea
    raw = target / max(price_eur, 0.01)
    if unit in {"KG", "L"}:
        step = 5 if raw >= 50 else 1
        return float(max(step, round(raw / step) * step))
    if unit == "M2":
        return float(max(10, round(raw / 10) * 10))
    if unit == "M3":
        return float(max(1, round(raw)))
    if unit == "BTL":
        return float(max(12, round(raw / 12) * 12))
    if unit in {"CTN", "BAG", "ROLL"}:
        return float(max(1, min(400, round(raw))))
    if unit in {"PAIRS", "SETS"}:
        return float(max(10, round(raw / 10) * 10))
    if price_eur >= 50:
        return float(max(1, round(raw)))
    if price_eur >= 10:
        return float(max(10, round(raw / 10) * 10))
    return float(max(100, round(raw / 100) * 100))


def build_lines(
    rng: random.Random,
    catalog: Catalog,
    archetype: str,
    lang: str,
    supplier_country: str,
    count: int,
    fx: float,
    currency: str,
) -> list[Line]:
    chapters = ARCHETYPE_CHAPTERS[archetype]
    weights = [CHAPTER_WEIGHTS[ch] for ch in chapters]
    lines: list[Line] = []
    used_codes: set[str] = set()

    for index in range(1, count + 1):
        for _ in range(40):
            chapter = rng.choices(chapters, weights=weights, k=1)[0]
            pool = [e for e in catalog.by_chapter.get(chapter, []) if _usable(e)]
            if not pool:
                continue
            entry = rng.choice(pool)
            if entry.cn8 in used_codes and len(pool) > 12:
                continue
            used_codes.add(entry.cn8)
            break
        else:
            continue

        base = _base_description(entry, lang)
        bits, kind = _modifier_bits(rng, entry, archetype, lang)
        description = _format_description(base, bits, lang, uppercase=rng.random() < 0.62)

        unit = rng.choice(_UNIT_BY_CHAPTER.get(chapter, ("PCS", "UNITS")))
        low, high = _price_range(chapter, archetype)
        # Distribución sesgada hacia precios bajos.
        price_eur = round(low * (high / low) ** (rng.random() ** 1.8), 2)
        if unit in {"KG", "L"} and price_eur < 1:
            price_eur = round(price_eur, 3)
        quantity = _quantity_for(unit, price_eur, rng)

        unit_price = round(price_eur * fx, 2)
        amount = round(quantity * unit_price, 2)

        if unit == "KG":
            net = quantity
        elif unit == "L":
            net = quantity * 1.0
        elif unit == "CTN":
            net = quantity * rng.uniform(6, 14)
        elif unit == "BAG":
            net = quantity * 25
        elif unit == "BTL":
            net = quantity * 0.75
        else:
            density = _EUR_PER_KG.get(chapter, 20) * rng.uniform(0.8, 1.3)
            kg_per_unit = max(0.05, price_eur / density)
            net = quantity * kg_per_unit
        gross = net * rng.uniform(1.04, 1.16)

        if unit in {"PCS", "PAIRS", "SETS", "UNITS"}:
            kg_per_unit = max(0.05, net / max(quantity, 1))
            per_carton = max(1, round(rng.uniform(8, 20) / kg_per_unit))
            packages = max(1, math.ceil(quantity / per_carton))
        elif unit == "CTN":
            packages = int(quantity)
        elif unit in {"BAG", "BTL"}:
            packages = max(1, math.ceil(quantity / (24 if unit == "BTL" else 12)))
        else:
            packages = max(1, math.ceil(net / 400))

        if archetype == "EXTRA_EU":
            origin = supplier_country if rng.random() < 0.78 else rng.choice(
                ("CN", "IN", "VN", "TR", "BD", "PK", "MA", "TW", "KR")
            )
        elif archetype == "INTRA_EU":
            origin = supplier_country if rng.random() < 0.85 else rng.choice(("DE", "FR", "IT", "PT", "NL", "PL", "BE", "ES"))
        else:
            origin = "ES"

        lines.append(
            Line(
                line_no=index,
                description=description,
                cn8=entry.cn8,
                hs6=entry.hs6,
                taric10=rng.choice(entry.taric10),
                origin=origin,
                quantity=quantity,
                unit=unit,
                unit_price=round(unit_price * fx, 2),
                amount=round(amount * fx, 2),
                net_weight=net,
                gross_weight=gross,
                packages=packages,
                kind=kind,
            )
        )

    # Recalcular importes con el precio ya convertido para que cuadre al céntimo.
    for line in lines:
        line.amount = round(line.quantity * line.unit_price, 2)
    return lines
