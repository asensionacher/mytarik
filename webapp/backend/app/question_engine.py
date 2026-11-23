"""Deterministic question selection from a candidate set.

The rule is simple: never ask an attribute already present in the product
description; ask only an attribute that splits the remaining candidates.
"""
from __future__ import annotations


import re
import unicodedata

MATERIALS = {
    "titanium": ("titan", "titanio", "titane", "titan"),
    "steel": ("steel", "acero", "acier", "stahl", "acciaio"),
    "aluminium": ("alumin", "aluminium", "aluminio", "aluminium"),
    "plastic": ("plastic", "plastico", "plástico", "plastique", "kunststoff"),
    "cotton": ("cotton", "algodon", "algodón", "coton", "baumwolle"),
}
CHAPTER_MATERIAL = {"73": "steel", "76": "aluminium", "81": "titanium", "39": "plastic", "52": "cotton", "61": "cotton", "62": "cotton"}
CODE_USE = {"8108909091": "aircraft"}
USE_PATTERNS = {
    "aircraft": ("aircraft", "aeronave", "aeronaut", "avion", "avión", "aeronef", "flugzeug", "aereo"),
    "medical": ("medical", "medico", "médico", "medical", "medizin", "medico"),
    "automotive": ("automotive", "automocion", "automoción", "automobile", "kraftfahrzeug", "automotive"),
}

L = {
    "es": {"aircraft": ("¿El producto está destinado a una aeronave?", ["Sí", "No"]), "material": ("¿De qué material está fabricado?", []), "form": ("¿Cuál es la forma o presentación exacta?", [])},
    "en": {"aircraft": ("Is the product intended for an aircraft?", ["Yes", "No"]), "material": ("What material is it made of?", []), "form": ("What is its exact form or presentation?", [])},
    "fr": {"aircraft": ("Le produit est-il destiné à un aéronef ?", ["Oui", "Non"]), "material": ("De quel matériau est-il fabriqué ?", []), "form": ("Quelle est sa forme ou présentation exacte ?", [])},
    "de": {"aircraft": ("Ist das Produkt für ein Luftfahrzeug bestimmt?", ["Ja", "Nein"]), "material": ("Aus welchem Material besteht es?", []), "form": ("Wie ist die genaue Form oder Aufmachung?", [])},
    "it": {"aircraft": ("Il prodotto è destinato a un aeromobile?", ["Sì", "No"]), "material": ("Di quale materiale è fatto?", []), "form": ("Qual è la forma o presentazione esatta?", [])},
}


def _plain(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value.lower()).strip()


def _known_material(description: str) -> str | None:
    text = _plain(description)
    for material, terms in MATERIALS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            return material
    return None


def _code_material(code: str) -> str | None:
    return CHAPTER_MATERIAL.get((code or "")[:2])


def _candidate_use(description: str, code: str = "") -> set[str]:
    text = _plain(description)
    uses = {use for use, terms in USE_PATTERNS.items() if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)}
    if CODE_USE.get(code):
        uses.add(CODE_USE[code])
    return uses


def _question(language: str, key: str, options: list[str] | None = None) -> dict:
    text, defaults = L.get(language, L["es"])[key]
    return {"question": text, "options": options if options is not None else defaults, "attribute": key}


def next_question(description: str, candidates: list[dict], language: str = "es") -> dict | None:
    """Return one question that separates current candidates, or None.

    ``candidates`` items use at least ``code`` and ``description``.
    A known material removes candidates from incompatible TARIC chapters and
    suppresses the material question entirely.
    """
    known_material = _known_material(description)
    filtered = []
    for candidate in candidates:
        code = str(candidate.get("code") or candidate.get("taric10") or candidate.get("cn8") or "")
        material = _code_material(code)
        if known_material and material and material != known_material:
            continue
        filtered.append({**candidate, "code": code})

    # Family-specific questions: use a real TARIC split, not a generic label.
    plain_description = _plain(description)
    names = set()
    if any(word in plain_description for word in ("bicicleta", "bicycle", "bicyclette", "fahrrad", "bicicletta")):
        names.add("bicycle")
    if any(word in plain_description for word in ("motos", "moto ", "motocicleta", "motorcycle", "motorbike", "moped", "scooter", "motorrad", "motocyclette", "motocicletta")):
        names.add("motorcycle")
    if any(word in plain_description for word in ("lona", "tarpaulin", "toldo", "awning", "canvas", "vela", "sail")):
        names.add("textile_canvas")
    if any(word in plain_description for word in ("cepillo de dientes", "toothbrush", "brosse a dents", "zahnburste", "spazzolino")):
        names.add("toothbrush")
    if any(word in plain_description for word in ("cable usb", "usb cable", "usb-c", "usb c", "cable de datos", "data cable", "charging cable", "cable de carga")):
        names.add("usb_cable")
    if any(word in plain_description for word in ("bascula", "báscula", "balanza", "scale", "weighing", "balance", "pesage", "waage", "bilancia")):
        names.add("scale")
    codes = {str(item.get("code") or "") for item in filtered}
    if "bicycle" in names and "8712003000" in codes and "rodamiento" not in _plain(description) and "ball bearing" not in _plain(description):
        return {"question": "¿La bicicleta incorpora rodamientos de bolas?", "options": ["Sí", "No"], "attribute": "ball_bearings"}
    if "bicycle" in names and any(code.startswith("8711") for code in codes) and "electric" not in _plain(description) and "electrica" not in _plain(description):
        return {"question": "¿La bicicleta es eléctrica?", "options": ["Sí", "No"], "attribute": "electric"}
    if "motorcycle" in names and len(codes) >= 2:
        return {"question": "¿Cuál es la cilindrada del motor de gasolina?", "options": ["Hasta 50 cc", "51–250 cc", "251–500 cc", "501–800 cc", "Más de 800 cc", "Eléctrica"], "attribute": "engine_cc"}
    if "textile_canvas" in names and any(code.startswith("6306") for code in codes):
        return {"question": "¿Qué tipo de artículo textil es?", "options": ["Lona o toldo", "Tienda de campaña", "Vela", "Otro"], "attribute": "textile_article"}
    if "toothbrush" in names and len(codes) >= 2 and not any(word in plain_description for word in ("electrico", "eléctrico", "electric", "manual")):
        return {"question": "¿El cepillo de dientes es manual o eléctrico?", "options": ["Manual", "Eléctrico", "Instrumento dental profesional"], "attribute": "toothbrush_type"}
    if "usb_cable" in names and len(codes) >= 1 and not any(word in plain_description for word in ("fibra", "optical", "optico", "óptico")):
        return {"question": "¿El cable USB lleva conectores en los extremos?", "options": ["Sí, con conectores", "No, sin conectores", "Es de fibra óptica"], "attribute": "usb_connectors"}
    if "scale" in names and len(codes) >= 1:
        return {"question": "¿Qué tipo de báscula es?", "options": ["Personal o cocina", "Industrial o comercial", "Precisión o laboratorio"], "attribute": "scale_type"}

    # If material is unknown and candidates belong to different materials, ask it.
    if not known_material:
        materials = {_code_material(item["code"]) for item in filtered} - {None}
        if len(materials) >= 2:
            options = sorted(materials)
            return _question(language, "material", options)

    # Aircraft is the most valuable discriminator after material.
    if "aircraft" not in _plain(description):
        uses = {use for item in filtered for use in _candidate_use(str(item.get("description") or ""), item["code"])}
        if "aircraft" in uses and len(filtered) >= 2:
            return _question(language, "aircraft")

    # If candidates still differ and there is no better deterministic split,
    # return a form question only when the caller explicitly needs one.
    return None


def filter_candidates(description: str, candidates: list[dict], attribute: str, answer: str) -> list[dict]:
    """Apply one answer to the current candidate set."""
    value = _plain(answer)
    positive = value in {"si", "sí", "yes", "oui", "ja", "vero", "true", "1"}
    negative = value in {"no", "non", "nein", "false", "0"}
    known_material = _known_material(description)
    base = []
    for candidate in candidates:
        code = str(candidate.get("code") or candidate.get("taric10") or candidate.get("cn8") or "")
        candidate_material = _code_material(code)
        if known_material and candidate_material and candidate_material != known_material:
            continue
        base.append({**candidate, "code": code})

    out = []
    for candidate in base:
        code = str(candidate.get("code") or "")
        if attribute == "material":
            material = _code_material(code)
            if material and material in value:
                out.append({**candidate, "code": code})
        elif attribute == "aircraft":
            is_aircraft = CODE_USE.get(code) == "aircraft" or "aircraft" in _candidate_use(str(candidate.get("description") or ""), code)
            if (positive and is_aircraft) or (negative and not is_aircraft) or (not positive and not negative):
                out.append({**candidate, "code": code})
        elif attribute == "ball_bearings":
            is_ball = code == "8712003000" or "ball bearing" in _plain(str(candidate.get("description") or ""))
            if (positive and is_ball) or (negative and not is_ball) or (not positive and not negative):
                out.append({**candidate, "code": code})
        elif attribute == "electric":
            is_electric = code.startswith("8711") or "electric" in _plain(str(candidate.get("description") or ""))
            if (positive and is_electric) or (negative and not is_electric) or (not positive and not negative):
                out.append({**candidate, "code": code})
        elif attribute == "scale_type":
            value_plain = _plain(value)
            if "precision" in value_plain or "laboratorio" in value_plain or "balanza" in value_plain:
                if code.startswith("9016"):
                    out.append({**candidate, "code": code})
            elif "industrial" in value_plain or "comercial" in value_plain:
                if code.startswith("8423") and not code.startswith("842310"):
                    out.append({**candidate, "code": code})
            else:
                if code.startswith("842310"):
                    out.append({**candidate, "code": code})
        elif attribute == "usb_connectors":
            value_plain = _plain(value)
            if "fibra" in value_plain or "optical" in value_plain:
                if code.startswith("854470"):
                    out.append({**candidate, "code": code})
            elif "no" in value_plain or "sin" in value_plain:
                if code.startswith("854449"):
                    out.append({**candidate, "code": code})
            else:
                if code.startswith("854442"):
                    out.append({**candidate, "code": code})
        elif attribute == "toothbrush_type":
            value_plain = _plain(value)
            if "electric" in value_plain or "eléctrico" in value_plain:
                if code.startswith("8509"):
                    out.append({**candidate, "code": code})
            elif "profesional" in value_plain or "instrumento" in value_plain:
                if code.startswith("9018"):
                    out.append({**candidate, "code": code})
            else:
                if code.startswith("9603"):
                    out.append({**candidate, "code": code})
        elif attribute == "ram_format":
            value_plain = _plain(value)
            if "modulo" in value_plain or "módulo" in value_plain or "dimm" in value_plain:
                if code.startswith("8473"):
                    out.append({**candidate, "code": code})
            else:
                if code.startswith(("8542", "8548")):
                    out.append({**candidate, "code": code})
        elif attribute == "textile_article":
            value_plain = _plain(value)
            if "lona" in value_plain or "toldo" in value_plain or "tarpaulin" in value_plain:
                if code.startswith(("630612", "630619")):
                    out.append({**candidate, "code": code})
            elif "tienda" in value_plain or "tent" in value_plain:
                if code.startswith(("630622", "630629")):
                    out.append({**candidate, "code": code})
            elif "vela" in value_plain or "sail" in value_plain:
                if code.startswith("630630"):
                    out.append({**candidate, "code": code})
            else:
                if not code.startswith(("630612", "630619", "630622", "630629", "630630", "630640")):
                    out.append({**candidate, "code": code})
        elif attribute == "engine_cc":
            ranges = {
                "871110": "hasta 50", "871120": "51 250", "871130": "251 500",
                "871140": "501 800", "871150": "mas de 800", "871160": "electrica",
            }
            wanted = next((bucket for prefix, bucket in ranges.items() if code.startswith(prefix)), "")
            if "electric" in value or "electrica" in value:
                match = "electrica"
            elif "hasta" in value:
                match = "hasta 50"
            elif "800" in value:
                match = "mas de 800"
            elif "501" in value:
                match = "501 800"
            elif "251" in value:
                match = "251 500"
            elif "51" in value or "250" in value:
                match = "51 250"
            else:
                match = ""
            if match and wanted == match:
                out.append({**candidate, "code": code})
        else:
            out.append({**candidate, "code": code})
    return out


def special_question(description: str, candidates: list[dict], language: str = "es") -> dict | None:
    text = _plain(description)
    codes = {str(c.get("code") or c.get("taric10") or c.get("cn8") or "") for c in candidates}
    if any(term in text for term in ("memoria ram", "memory ram", "dimm", "so dimm", "ram")):
        if any(code.startswith("8473") for code in codes) or any(code.startswith("8542") for code in codes):
            return {
                "question": "¿La memoria RAM es un módulo ensamblado (DIMM/SO-DIMM) o un chip DRAM/SRAM suelto?",
                "options": ["Módulo ensamblado (DIMM/SO-DIMM)", "Chip DRAM/SRAM suelto"],
                "attribute": "ram_format",
            }
    return None
