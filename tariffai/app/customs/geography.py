"""
Validación geográfica previa: intracomunitario vs. país tercero.

Antes de tocar ningún servidor externo se decide si la operación es:

- intracomunitaria (no hay DUA ni aranceles; sí Intrastat e IVA intracomunitario),
- intracomunitaria con excepción territorial (Åland, Açores/Madeira, Canarias,
  Ceuta y Melilla: el IVA y/o el ámbito aduanero cambian),
- importación desde país tercero (TARIC completo),
- exportación a país tercero (la UE no grava; mandan sanciones y doble uso).

Los datos de entrada son códigos ISO-2; las excepciones territoriales se
resuelven con la subdivisión ISO 3166-2 opcional (`ES-CN`, `ES-CE`, `ES-ML`,
`PT-20`, `PT-30`). `AX` (Åland) es un ISO-2 propio y se detecta solo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.customs.schemas import (
    CustomsRegime,
    OperationType,
    ReportingRequirement,
)


# ── Territorios ────────────────────────────────────────────────────────

EU_MEMBER_STATES: frozenset[str] = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
})

# Territorios europeos con régimen propio dentro de la Unión.
AX: str = "AX"  # Åland (Islas Aland) — territorio aduanero UE, fuera del IVA UE

#: Subdivisiones con régimen fiscal especial.
SPECIAL_SUBDIVISIONS: dict[str, dict[str, str]] = {
    "ES-CN": {
        "label": "Canarias",
        "vat_regime": "IGIC",
        "in_customs_territory": "false",
        "note": (
            "Canarias: territorio excluido del territorio aduanero y del IVA de la UE. "
            "La importación a Canarias lleva DUA, arancel exterior canario e IGIC "
            "(en lugar de IVA)."
        ),
    },
    "ES-CE": {
        "label": "Ceuta",
        "vat_regime": "AIEM",
        "in_customs_territory": "false",
        "note": (
            "Ceuta: territorio excluido del territorio aduanero y del IVA de la UE. "
            "La importación lleva DUA y AIEM (Arbitrio de importación) en lugar de IVA."
        ),
    },
    "ES-ML": {
        "label": "Melilla",
        "vat_regime": "AIEM",
        "in_customs_territory": "false",
        "note": (
            "Melilla: territorio excluido del territorio aduanero y del IVA de la UE. "
            "La importación lleva DUA y AIEM en lugar de IVA."
        ),
    },
    "PT-20": {
        "label": "Açores",
        "vat_regime": "VAT_REDUCED",
        "in_customs_territory": "true",
        "note": (
            "Açores: dentro del territorio aduanero de la UE pero con IVA regional "
            "reducido; el tráfico con la UE continental no genera IVA intracomunitario "
            "ni DUA, pero sí Intrastat."
        ),
    },
    "PT-30": {
        "label": "Madeira",
        "vat_regime": "VAT_REDUCED",
        "in_customs_territory": "true",
        "note": (
            "Madeira: dentro del territorio aduanero de la UE pero con IVA regional "
            "reducido; el tráfico con la UE continental no genera IVA intracomunitario "
            "ni DUA, pero sí Intrastat."
        ),
    },
    "AX": {
        "label": "Åland",
        "vat_regime": "AX",
        "in_customs_territory": "true",
        "note": (
            "Åland: dentro del territorio aduanero de la UE pero fuera del territorio "
            "de IVA de la UE. No hay arancel, pero la importación lleva IVA de Åland "
            "y no hay IVA intracomunitario."
        ),
    },
}

#: Territorios excluidos del territorio aduanero y de IVA de la UE.
EXCLUDED_TERRITORIES: frozenset[str] = frozenset({"ES-CN", "ES-CE", "ES-ML"})

#: Países bajo medidas restrictivas de la UE (congelamiento de activos/sanciones).
SANCTIONED_COUNTRIES: frozenset[str] = frozenset({"RU", "BY", "IR", "KP", "SY"})


@dataclass(frozen=True)
class TerritorialStatus:
    """Situación territorial de un extremo de la operación."""

    country: str
    label: str
    subdivision: str | None = None
    in_eu_customs_territory: bool = False
    in_eu_vat_territory: bool = False
    vat_regime: str = "NONE"
    special_regime: bool = False
    note: str = ""

    @property
    def is_eu_member(self) -> bool:
        return self.country in EU_MEMBER_STATES


@dataclass(frozen=True)
class GeographicalAssessment:
    """Resultado de la validación geográfica de la operación."""

    regime: CustomsRegime
    origin: TerritorialStatus
    destination: TerritorialStatus
    reporting_requirements: list[ReportingRequirement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requires_taric_consultation: bool = False
    intra_union: bool = False
    duties_apply: bool = True

    @property
    def territorial_note(self) -> str | None:
        return " ".join(self.notes) if self.notes else None


def _resolve(country: str, subdivision: str | None) -> TerritorialStatus:
    """Resuelve país + subdivisión a su situación territorial."""
    country = country.upper()
    key = subdivision.upper() if subdivision else None

    if country == AX or key == "AX":
        spec = SPECIAL_SUBDIVISIONS["AX"]
        return TerritorialStatus(
            country=country,
            label=spec["label"],
            subdivision=key,
            in_eu_customs_territory=True,
            in_eu_vat_territory=False,
            vat_regime=spec["vat_regime"],
            special_regime=True,
            note=spec["note"],
        )

    is_member = country in EU_MEMBER_STATES
    if is_member and key and key in SPECIAL_SUBDIVISIONS:
        spec = SPECIAL_SUBDIVISIONS[key]
        excluded = spec["in_customs_territory"] == "false"
        return TerritorialStatus(
            country=country,
            label=spec["label"],
            subdivision=key,
            in_eu_customs_territory=not excluded,
            in_eu_vat_territory=not excluded,
            vat_regime=spec["vat_regime"],
            special_regime=True,
            note=spec["note"],
        )

    return TerritorialStatus(
        country=country,
        label=country,
        subdivision=key,
        in_eu_customs_territory=is_member,
        in_eu_vat_territory=is_member,
        vat_regime="EU" if is_member else "NONE",
    )


def _reporting(
    origin: TerritorialStatus,
    destination: TerritorialStatus,
    intra_union: bool,
    operation_type: OperationType,
) -> list[ReportingRequirement]:
    """Obligaciones de información statistics y fiscales de la operación."""
    requirements: list[ReportingRequirement] = []

    if intra_union:
        same_territory = (
            origin.country == destination.country
            and origin.subdivision == destination.subdivision
        )
        if not same_territory:
            requirements.append(ReportingRequirement.INTRSTAT)
        if origin.vat_regime == "AX" or destination.vat_regime == "AX":
            requirements.append(ReportingRequirement.AX_VAT)
        elif origin.vat_regime == "VAT_REDUCED" or destination.vat_regime == "VAT_REDUCED":
            # El IVA regional sustituye al IVA intracomunitario.
            pass
        elif (
            origin.in_eu_vat_territory
            and destination.in_eu_vat_territory
            and not same_territory
        ):
            requirements.append(ReportingRequirement.VAT_INTRA_COMMUNITY)
        return requirements

    eu_side = origin if origin.is_eu_member or origin.country == AX else destination
    other_side = destination if eu_side is origin else origin

    if eu_side.vat_regime == "IGIC":
        requirements.append(ReportingRequirement.IGIC)
    if eu_side.vat_regime == "AIEM":
        requirements.append(ReportingRequirement.AIEM)
    if eu_side.vat_regime == "EU" and operation_type == "IMPORT":
        requirements.append(ReportingRequirement.VAT_IMPORT)

    if operation_type == "IMPORT":
        requirements.append(ReportingRequirement.CUSTOMS_DECLARATION)
    else:
        requirements.append(ReportingRequirement.EXPORT_DECLARATION)

    if other_side.country in SANCTIONED_COUNTRIES:
        requirements.append(ReportingRequirement.EXPORT_DECLARATION)
    return requirements


def assess_geography(
    origin_country: str,
    destination_country: str,
    operation_type: OperationType,
    origin_subdivision: str | None = None,
    destination_subdivision: str | None = None,
) -> GeographicalAssessment:
    """
    Evalúa el territorio de la operación antes de cualquier consulta externa.
    """
    origin = _resolve(origin_country, origin_subdivision)
    destination = _resolve(destination_country, destination_subdivision)
    notes: list[str] = []

    both_in_union = origin.in_eu_customs_territory and destination.in_eu_customs_territory
    both_in_vat = origin.in_eu_vat_territory and destination.in_eu_vat_territory
    same_member_state = origin.country == destination.country

    # --- Ambos lados en la unión aduanera y de IVA -------------------------
    if both_in_union and both_in_vat:
        if origin.special_regime or destination.special_regime:
            # Región con régimen fiscal propio dentro de la unión aduanera.
            regime = CustomsRegime.INTRA_UNION_TERRITORIAL_EXCEPTION
            for side in (origin, destination):
                if side.note:
                    notes.append(side.note)
            notes.append(
                "El tráfico con la región de IVA reducido no genera IVA intracomunitario: "
                "aplica el IVA regional en destino y el movimiento se declara en Intrastat."
            )
            return GeographicalAssessment(
                regime=regime,
                origin=origin,
                destination=destination,
                reporting_requirements=_reporting(origin, destination, True, operation_type),
                notes=notes,
                requires_taric_consultation=False,
                intra_union=True,
                duties_apply=False,
            )
        if same_member_state and origin.subdivision == destination.subdivision:
            regime = CustomsRegime.INTRA_UNION
            notes.append(
                "Operación dentro del mismo Estado Miembro: sin Intrastat, sin DUA "
                "y sin IVA intracomunitario."
            )
        else:
            regime = CustomsRegime.INTRA_UNION
            notes.append(
                "Operación intracomunitaria: no se aplica DUA ni arancel. "
                "Corresponde Intrastat y autoliquidación del IVA intracomunitario."
            )
        return GeographicalAssessment(
            regime=regime,
            origin=origin,
            destination=destination,
            reporting_requirements=_reporting(origin, destination, True, operation_type),
            notes=notes,
            requires_taric_consultation=False,
            intra_union=True,
            duties_apply=False,
        )

    # --- Unión aduanera con excepción territorial --------------------------
    if both_in_union:
        regime = CustomsRegime.INTRA_UNION_TERRITORIAL_EXCEPTION
        for side in (origin, destination):
            if side.note:
                notes.append(side.note)
        if origin.vat_regime == "AX" or destination.vat_regime == "AX":
            notes.append(
                "No se consultan aranceles: el tráfico con Åland no está sujeto a derechos "
                "aduaneros dentro de la Unión."
            )
        elif origin.vat_regime == "VAT_REDUCED" or destination.vat_regime == "VAT_REDUCED":
            notes.append(
                "No se consultan aranceles: el tráfico con la región portuguesa de IVA "
                "reducido está dentro del territorio aduanero de la UE."
            )
        return GeographicalAssessment(
            regime=regime,
            origin=origin,
            destination=destination,
            reporting_requirements=_reporting(origin, destination, True, operation_type),
            notes=notes,
            requires_taric_consultation=False,
            intra_union=True,
            duties_apply=False,
        )

    # --- Territorio excluido (Canarias, Ceuta, Melilla) -------------------
    if origin.subdivision in EXCLUDED_TERRITORIES or destination.subdivision in EXCLUDED_TERRITORIES:
        excluded = origin if origin.subdivision in EXCLUDED_TERRITORIES else destination
        notes.append(excluded.note)
        if operation_type == "IMPORT":
            regime = CustomsRegime.IMPORT_FROM_THIRD_COUNTRY
        else:
            regime = CustomsRegime.EXPORT_TO_THIRD_COUNTRY
        notes.append(
            "El arancel exterior aplicable al territorio excluido se publica por la "
            "autoridad española (AAC en Canarias, AIEM en Ceuta y Melilla); el TARIC "
            "consultado es el arancel exterior común de la Unión."
        )
        return GeographicalAssessment(
            regime=regime,
            origin=origin,
            destination=destination,
            reporting_requirements=_reporting(origin, destination, False, operation_type),
            notes=notes,
            requires_taric_consultation=True,
            intra_union=False,
            duties_apply=True,
        )

    # --- País tercero ------------------------------------------------------
    eu_side = origin if origin.is_eu_member or origin.country == AX else destination
    if operation_type == "IMPORT":
        regime = CustomsRegime.IMPORT_FROM_THIRD_COUNTRY
        notes.append(
            "Importación desde país tercero: se consultan las medidas TARIC vigentes "
            "en la Unión Europea para la partida, el origen y el destino."
        )
    else:
        regime = CustomsRegime.EXPORT_TO_THIRD_COUNTRY
        notes.append(
            "Exportación a país tercero: la Unión no grava las exportaciones, por lo que "
            "no hay arancel de importación que aplicar. Los aranceles del país destino "
            "quedan fuera del TARIC; en esta operación son relevantes las prohibiciones, "
            "las sanciones y las licencias de doble uso."
        )
        if destination.country in SANCTIONED_COUNTRIES:
            notes.append(
                f"El país destino ({destination.country}) está sujeto a medidas restrictivas "
                "de la UE: verifica el lista consolidada de sanciones antes de despachar."
            )
    return GeographicalAssessment(
        regime=regime,
        origin=origin,
        destination=destination,
        reporting_requirements=_reporting(origin, destination, False, operation_type),
        notes=notes,
        requires_taric_consultation=True,
        intra_union=False,
        duties_apply=True,
    )


def is_intra_union(origin_country: str, destination_country: str) -> bool:
    """Atajo: ambos extremos dentro del territorio aduanero y de IVA de la UE."""
    origin = _resolve(origin_country, None)
    destination = _resolve(destination_country, None)
    return (
        origin.in_eu_customs_territory
        and destination.in_eu_customs_territory
        and origin.in_eu_vat_territory
        and destination.in_eu_vat_territory
    )
