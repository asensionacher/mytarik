"""Deterministic product-family headings for retrieval.

The LLM and EBTI are useful, but a bicycle must never be searched among
caravans or sewing machines. These rules are deliberately narrow: when they
match, retrieval is restricted to the heading family and irrelevant codes are
removed before the question engine sees them.
"""
from __future__ import annotations

import re
import unicodedata

RULES = [
    {
        "name": "scale",
        "keywords": ("bascula", "báscula", "balanza", "scale", "weighing", "balance", "pesage", "waage", "bilancia"),
        "headings": ("8423", "9016"),
    },
    {
        "name": "usb_cable",
        "keywords": ("cable usb", "usb cable", "usb-c", "usb c", "cable de datos", "data cable", "charging cable", "cable de carga"),
        "headings": ("8544",),
    },
    {
        "name": "toothbrush",
        "keywords": ("cepillo de dientes", "toothbrush", "brosse a dents", "zahnburste", "spazzolino"),
        "headings": ("9603", "8509", "9018"),
    },
    {
        "name": "textile_canvas",
        "keywords": ("lona", "tarpaulin", "toldo", "awning", "canvas", "vela", "sail", "carpa", "tent"),
        "headings": ("6306",),
    },
    {
        "name": "bicycle_parts",
        "keywords": ("manillar", "handlebar", "guidon", "lenker", "manubrio", "cuadro de bicicleta", "bicycle frame", "horquilla de bicicleta", "pedal", "sillin", "saddle", "rueda de bicicleta", "bicycle wheel", "componente de bicicleta"),
        "headings": ("8714",),
        "subheadings": ("871499",),
        "terms": ("handlebar", "manillar", "guidon", "lenker", "manubrio", "stem"),
    },
    {
        "name": "motorcycle",
        "keywords": ("motos", "moto ", "motocicleta", "motocicletas", "motorcycle", "motorcycles", "motorbike", "moped", "scooter", "motorrad", "motocyclette", "motocicletta"),
        "headings": ("8711",),
    },
    {
        "name": "bicycle",
        "keywords": ("bicicleta", "bicycle", "bicyclette", "fahrrad", "bicicletta", "bike"),
        "headings": ("8712",),
    },
    {
        "name": "titanium_screw",
        "keywords": ("titanio", "titanium", "titane", "titan"),
        "headings": ("8108",),
    },
    {
        "name": "steel_screw",
        "keywords": ("tornillo", "screw", "bolt", "vis", "schraube", "vite"),
        "headings": ("7318", "8108"),
    },
    {
        "name": "aluminium",
        "keywords": ("aluminio", "aluminium", "aluminum", "aluminium", "alluminio"),
        "headings": ("7601", "7604", "7606", "7608", "7610", "7616"),
    },
]


def _plain(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value.lower()).strip()


def family_hints(text: str) -> list[dict]:
    value = _plain(text)
    for rule in RULES:
        # Substring match handles plurals/inflections (bicicleta -> bicicletas).
        if any(word in value for word in rule["keywords"]):
            return [
                {
                    "heading": heading,
                    "cn8": "",
                    "description": rule["name"],
                    "strict": True,
                    "subheading": (rule.get("subheadings") or [""])[0],
                    "terms": rule.get("terms", ()),
                }
                for heading in rule["headings"]
            ]
    return []
