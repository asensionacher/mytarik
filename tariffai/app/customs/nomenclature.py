"""
Resolución de un código HS de 6 dígitos a sus códigos TARIC de 10 dígitos.

El clasificador devuelve códigos HS de 6 dígitos, pero las medidas del TARIC
se definen sobre códigos de 10 dígitos (nomenclatura combinada de 8 dígitos +
2 dígitos de subdivisión TARIC). El último dígito no es un detalle: cambia el
arancel, así que la elección es del declarante y la UI la presenta.

La fuente es la nomenclatura de Access2Markets
(`api/v2/nomenclature/productsByCode`), que devuelve el árbol de nomenclatura
con los descendientes del código pedido:

    610910 → 6109100010 "T-shirts" · 6109100090 "Other"

El árbol no es completo: hay ramas sin descendientes y, cuando la
subdivisión TARIC no existe, el código de 8 dígitos no aparece. Cuando no hay
nada mejor, se propone el código de 8 dígitos terminado en "00" con el
sufijo TARIC "00" (`{hs_code}0000`) marcado como inferido para que quien lo
use lo verifique.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.customs.schemas import TaricCandidate

logger = logging.getLogger(__name__)

#: Sufijo TARIC por defecto cuando la partida no tiene subdivisión.
TARIC_SUFFIX = "00"


@dataclass(frozen=True)
class NomenclatureNode:
    code: str
    description: str


def collect_nodes(payload: Any) -> list[NomenclatureNode]:
    """Extrae todos los nodos con código del árbol de nomenclatura."""
    nodes: list[NomenclatureNode] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        code = str(node.get("code") or "").strip()
        if code:
            nodes.append(NomenclatureNode(
                code=code, description=str(node.get("description") or "").strip(),
            ))
        for child in node.get("children") or []:
            walk(child)

    if isinstance(payload, list):
        for root in payload:
            walk(root)
    else:
        walk(payload)
    return nodes


def build_candidates(nodes: list[NomenclatureNode], hs_code: str) -> list[TaricCandidate]:
    """
    Convierte los nodos de la nomenclatura en candidatos TARIC de 10 dígitos.

    - Un nodo de 10 dígitos ya es el código TARIC.
    - Un nodo de 8 dígitos es la nomenclatura combinada: se le añade el
      sufijo TARIC por defecto.
    - Si no hay ninguno, se propone `{hs_code}0000` marcado como inferido.
    """
    candidates: list[TaricCandidate] = []
    seen: set[str] = set()
    for node in nodes:
        if len(node.code) == 10:
            taric_code, exact = node.code, True
        elif len(node.code) == 8:
            taric_code, exact = node.code + TARIC_SUFFIX, True
        else:
            continue
        if taric_code in seen:
            continue
        seen.add(taric_code)
        candidates.append(TaricCandidate(
            taric_code=taric_code,
            description=node.description,
            exact=exact,
            source="nomenclature",
        ))

    if candidates:
        return candidates

    inferred = f"{hs_code}{TARIC_SUFFIX}{TARIC_SUFFIX}"
    return [TaricCandidate(
        taric_code=inferred,
        description="",
        exact=False,
        source="inferred",
    )]
