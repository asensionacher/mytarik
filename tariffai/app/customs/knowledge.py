"""
Base regulatoria no arancelaria codificada.

El TARIC sólo contiene medidas arancelarias y para-arancelarias: ni CBAM, ni
EUDR, ni RoHS, ni los certificados veterinarios o fitosanitarios de los
puestos de control fronterizo aparecen en `tariffs/get`. Esa información vive
en la normativa de la UE y en el catálogo de requisitos de Access2Markets.

Aquí se codifican las reglas deterministas (por capítulo de la nomenclatura y
por país) que permiten señalar qué régimen aplica a una partida. Cada entrada
declara su fuente (`knowledge_base`) y su referencia normativa, de forma que la
UI pueda distinguir lo verificado en la fuente en vivo de lo que procede de
esta base y deba confirmarse con la autoridad competente.

Cuando Access2Markets devuelve el requisito correspondiente (por ejemplo
"Marketing of products containing fluorinated greenhouse gases"), el requisito
en vivo sustituye a la entrada de esta base y se marca con su fuente real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.customs.schemas import (
    BorderControl,
    BorderControlCategory,
    DataSource,
    SpecialRegulation,
    SpecialRegulationKind,
)


@dataclass(frozen=True)
class Bilingual:
    """Texto con su traducción es/en."""

    es: str
    en: str

    def text(self, language: str) -> str:
        return self.es if language == "es" else self.en


@dataclass(frozen=True)
class RegulatoryRule:
    """Regla regulatoria aplicable a un conjunto de prefijos de partida."""

    kind: SpecialRegulationKind
    name: Bilingual
    reference: str
    prefixes: tuple[str, ...]
    reason: Bilingual
    action: Bilingual
    applies_to_import: bool = True
    applies_to_export: bool = True
    extra: dict[str, str] = field(default_factory=dict)


def _rule(
    kind: SpecialRegulationKind,
    name: tuple[str, str],
    reference: str,
    prefixes: tuple[str, ...],
    reason: tuple[str, str],
    action: tuple[str, str],
    **kwargs: object,
) -> RegulatoryRule:
    return RegulatoryRule(
        kind=kind,
        name=Bilingual(*name),
        reference=reference,
        prefixes=prefixes,
        reason=Bilingual(*reason),
        action=Bilingual(*action),
        **kwargs,  # type: ignore[arg-type]
    )


# ── Reglas ─────────────────────────────────────────────────────────────

CBAM_RULE = _rule(
    SpecialRegulationKind.CBAM,
    (
        "Mecanismo de Ajuste en Frontera por Carbono (CBAM)",
        "Carbon Border Adjustment Mechanism (CBAM)",
    ),
    "Reglamento (UE) 2023/956",
    (
        "2603",     # ferroaleaciones
        "72",       # hierro y acero
        "7601", "7603", "7604", "7605", "7606", "7608", "7609",
        "7610", "7611", "7612", "7613", "7614", "7616",
        "252310", "252320",   # cemento
        "2808", "2814", "283421", "283429",   # fertilizantes
        "271600",             # electricidad
        "2804",               # hidrógeno
    ),
    (
        "La partida está dentro del anexo I del CBAM: el importador debe "
        "declarar las emisiones embebidas y adquirir los certificados CBAM "
        "correspondientes.",
        "The line falls under CBAM annex I: the importer must declare embedded "
        "emissions and surrender the corresponding CBAM certificates.",
    ),
    (
        "Solicita los certificados CBAM al importador CBAM y presenta la "
        "declaración de emisiones en la aduana.",
        "Request CBAM certificates from the CBAM importer and file the emission "
        "declaration with customs.",
    ),
)

EUDR_RULE = _rule(
    SpecialRegulationKind.EUDR,
    (
        "Reglamento de Deforestación Libre de Arranque (EUDR)",
        "Deforestation-Free Products Regulation (EUDR)",
    ),
    "Reglamento (UE) 2023/1115",
    (
        "0101", "010121", "010122", "010129",   # bovinos
        "0901",                                  # café
        "1201", "1202", "120300", "120400",      # soja y sus derivados
        "150710", "151010",                      # aceite de palma
        "1801", "1802", "180310", "180320",      # cacao
        "400122", "400131", "400132", "400139",  # caucho
        "4401", "4402", "4403", "4404", "4405", "4406", "4407", "4408",
        "4409", "4410", "4411", "4412", "4413", "4414", "4415", "4416",
        "4417", "4418", "4419", "4420", "4421",
        "4701", "4702", "4703", "4704", "4705", "4706",
        "4801", "4802", "4803", "4804", "4805", "4806",
        "4911",
    ),
    (
        "La partida contiene madera, caucho, cacao, café, soja, aceite de palma o "
        "carne de bovino: está sujeta a la declaración de debida diligencia y al "
        "geolocalización del agente que la introduce en la UE.",
        "The line contains wood, rubber, cocoa, coffee, soy, palm oil or beef: it is "
        "subject to the due-diligence statement and to the geolocation of the operator "
        "placing it on the EU market.",
    ),
    (
        "Presenta una declaración de debida diligencia (DDS) válida y referencia el "
        "geolocalizador del producto en la aduana.",
        "File a valid due-diligence statement (DDS) and reference the product "
        "geolocation in the customs declaration.",
    ),
)

ROHS_RULE = _rule(
    SpecialRegulationKind.ROHS,
    (
        "Restricción de sustancias peligrosas en equipos eléctricos y electrónicos (RoHS)",
        "Restriction of Hazardous Substances in electrical and electronic equipment (RoHS)",
    ),
    "Directiva 2011/65/UE y Directiva (UE) 2015/863",
    ("84", "85"),
    (
        "La partida parece pertenecer a un equipo eléctrico o electrónico: el "
        "fabricante debe cumplir los límites de sustancias peligrosas y la "
        "declaración de conformidad.",
        "The line looks like electrical or electronic equipment: the manufacturer must "
        "comply with the hazardous-substance limits and with the declaration of conformity.",
    ),
    (
        "Solicita al proveedor la declaración de conformidad CE y la declaración de "
        "materiales conforme al Anexo II de RoHS.",
        "Ask the supplier for the CE declaration of conformity and the RoHS annex II "
        "material declaration.",
    ),
)

F_GAS_RULE = _rule(
    SpecialRegulationKind.F_GAS,
    (
        "Gases fluorados de efecto invernadero (F-gas)",
        "Fluorinated greenhouse gases (F-gas)",
    ),
    "Reglamento (UE) 2024/573",
    (
        "2901", "2902", "2903", "2904", "2905", "2906", "2907", "2908", "2909", "2910",
        "3907", "3908", "3909", "3910", "3911", "3912", "3913",
        "8414", "8415", "8417", "8418", "8419", "8422", "8474",
    ),
    (
        "La partida contiene gases fluorados o equipos que los contienen: su "
        "comercialización en la UE exige certificación, etiquetado y, según el "
        "Anexo IV, control de fugas.",
        "The line contains F-gases or equipment that contains them: placing it on the "
        "EU market requires certification, labelling and, under annex IV, leak checks.",
    ),
    (
        "Verifica la certificación de la instalación y el etiquetado F-gas del "
        "equipo y comprueba el certificado de fugas.",
        "Check the installation certificate, the F-gas label of the equipment and the "
        "leak-check certificate.",
    ),
)

REACH_RULE = _rule(
    SpecialRegulationKind.REACH,
    (
        "Registro, evaluación, autorización y restricción de sustancias químicas (REACH)",
        "Registration, Evaluation, Authorisation and Restriction of Chemicals (REACH)",
    ),
    "Reglamento (CE) n.º 1907/2006",
    ("28", "29", "38"),
    (
        "La partida es una sustancia o mezcla química: debe tener ficha de datos de "
        "seguridad y, si la sustancia está en la lista de autorizaciones, un permiso "
        "de la ECHA.",
        "The line is a chemical substance or mixture: it needs a safety data sheet and, "
        "if the substance is on the authorisation list, an ECHA permit.",
    ),
    (
        "Pide al proveedor la ficha de datos de seguridad (SDS) y comprueba si la "
        "sustancia está en el anexo XIV con autorización o restringida.",
        "Request the safety data sheet (SDS) from the supplier and check whether the "
        "substance is annexed XIV with authorisation or restriction.",
    ),
)

WEEE_RULE = _rule(
    SpecialRegulationKind.WEEE,
    (
        "Residuos de equipos eléctricos y electrónicos (WEEE)",
        "Waste electrical and electronic equipment (WEEE)",
    ),
    "Directiva 2012/19/UE",
    ("84", "85"),
    (
        "La partida parece un equipo eléctrico o electrónico: el productor debe estar "
        "inscrito en el registro de gestores de residuos de cada Estado Miembro.",
        "The line looks like electrical or electronic equipment: the producer must be "
        "registered with the waste scheme of each Member State.",
    ),
    (
        "Comprueba que el importador está registrado como productor en los registros "
        "WEEE aplicables.",
        "Check that the importer is registered as a producer in the relevant WEEE "
        "registers.",
    ),
)

DUAL_USE_RULE = _rule(
    SpecialRegulationKind.DUAL_USE,
    (
        "Bienes de doble uso (control de exportación)",
        "Dual-use goods (export control)",
    ),
    "Reglamento (UE) 2021/821",
    (
        "2801", "2804", "2805", "2806", "2807", "2808", "2809", "2810", "2811", "2812",
        "2813", "2814", "2815", "2816", "2817", "2818", "2819", "2820", "2821", "2822",
        "2823", "2824", "2825", "2826", "2827", "2828", "2829", "2830", "2831", "2832",
        "2833", "2834", "2835", "2836", "2837", "2838", "2839", "2840", "2841", "2842",
        "2843", "2844", "2845", "2846", "2847", "2848", "2849", "2850", "2851", "2852",
        "2853", "2854", "2855", "2856", "2857", "2858", "2859", "2860", "2861", "2862",
        "2863", "2864", "2865", "2866", "2867", "2868", "2869", "2870", "2871", "2872",
        "2873", "2874", "2875", "2876", "2877", "2878", "2879", "2880", "2881", "2882",
        "2883", "2884", "2885", "2886", "2887", "2888", "2889", "2890", "2891", "2892",
        "2893", "2894", "2895", "2896", "2897", "2898", "2899", "2900", "2901", "2902",
        "2903", "2904", "2905", "2906", "2907", "2908", "2909", "2910",
        "3601", "3602", "3603", "3604",
        "9301", "9302", "9303", "9304", "9305", "9306", "9307",
    ),
    (
        "La partida puede estar clasificada como bien de doble uso: la exportación "
        "fuera de la UE requiere licencia de exportación de la autoridad nacional "
        "competente y control previo a la exportación.",
        "The line may be classified as a dual-use item: exporting it outside the EU "
        "requires an export licence from the national competent authority and catch-all "
        "control.",
    ),
    (
        "Solicita la licencia de exportación (o la ficha de la EZ/system) y la "
        "aprobación por escrito del importador final antes de embarcar.",
        "Apply for the export licence (or the catch-all sheet) and the end-user "
        "statement before shipping.",
    ),
)

#: Reglas de producto industrial controladas por SOIVRE en España.
SOIVRE_PREFIXES: tuple[str, ...] = (
    "28", "29", "38", "39", "40", "61", "62", "64", "73", "84", "85", "87", "94", "95",
)

#: Capítulos de productos de origen animal (control veterinario en frontera).
ANIMAL_ORIGIN_CHAPTERS: tuple[str, ...] = ("01", "02", "03", "04", "05", "15", "16")

#: Capítulos de productos de origen vegetal (control fitosanitario en frontera).
PLANT_ORIGIN_CHAPTERS: tuple[str, ...] = ("06", "07", "08", "09", "10", "11", "12", "13", "14")

RULES: tuple[RegulatoryRule, ...] = (
    CBAM_RULE,
    EUDR_RULE,
    ROHS_RULE,
    F_GAS_RULE,
    REACH_RULE,
    WEEE_RULE,
    DUAL_USE_RULE,
)


# ── Coincidencia ───────────────────────────────────────────────────────


def _matches(prefixes: tuple[str, ...], code: str) -> bool:
    return any(code.startswith(prefix) for prefix in prefixes)


def match_special_regulations(
    taric_code: str,
    language: str = "en",
    operation_type: str = "IMPORT",
    destination_country: str | None = None,
) -> list[SpecialRegulation]:
    """Reglas de la base de conocimiento que aplican a la partida."""
    found: list[SpecialRegulation] = []
    for rule in RULES:
        if not _matches(rule.prefixes, taric_code):
            continue
        if operation_type == "IMPORT" and not rule.applies_to_import:
            continue
        if operation_type == "EXPORT" and not rule.applies_to_export:
            continue
        found.append(SpecialRegulation(
            regulation=rule.kind,
            name=rule.name.text(language),
            applies=True,
            reference=rule.reference,
            reason=rule.reason.text(language),
            action_required=rule.action.text(language),
            source=DataSource.KNOWLEDGE_BASE,
        ))

    if destination_country and destination_country.upper() in {"RU", "BY", "IR", "KP", "SY"}:
        found.append(SpecialRegulation(
            regulation=SpecialRegulationKind.SANCTIONS,
            name=Bilingual(
                "Medidas restrictivas de la Unión Europea",
                "European Union restrictive measures",
            ).text(language),
            applies=True,
            reference="Reglamento (UE) n.º 833/2014 y normativa de sanciones sectoriales",
            reason=Bilingual(
                f"El país de destino ({destination_country.upper()}) está sujeto a "
                "medidas restrictivas: pueden prohibir o condicionar la exportación "
                "y exigir autorización previa o prohibición.",
                f"The destination country ({destination_country.upper()}) is subject to "
                "restrictive measures: exports may be prohibited or require prior "
                "authorisation.",
            ).text(language),
            action_required=Bilingual(
                "Verifica el producto en la lista consolidada de sanciones de la UE y "
                "obtén la autorización correspondiente si procede.",
                "Check the product against the EU consolidated sanctions list and obtain "
                "the relevant authorisation if required.",
            ).text(language),
            source=DataSource.KNOWLEDGE_BASE,
        ))
    return found


def match_border_controls(
    taric_code: str,
    language: str = "en",
    country: str = "ES",
) -> list[BorderControl]:
    """Controles fronterizos deterministas (PCF, CHED, SOIVRE)."""
    controls: list[BorderControl] = []
    chapter = taric_code[:2]

    if chapter in ANIMAL_ORIGIN_CHAPTERS:
        controls.append(BorderControl(
            category=BorderControlCategory.SPS,
            code="CHED-A",
            title=Bilingual(
                "Certificado sanitario animal (CHED-A) y control en puesto fronterizo",
                "Animal health certificate (CHED-A) and border control post check",
            ).text(language),
            authority="PCF",
            requirement=Bilingual(
                "Los productos de origen animal se someten a control veterinario en un "
                "puesto de control fronterizo: se exige CHED-A en el MSC y control "
                "veterinario previo a la puesta en libre práctica.",
                "Products of animal origin are subject to veterinary checks at a border "
                "control post: a CHED-A is required in the MSC and the goods are "
                "released only after veterinary control.",
            ).text(language),
            mandatory=True,
            source=DataSource.KNOWLEDGE_BASE,
        ))
    elif chapter in PLANT_ORIGIN_CHAPTERS:
        controls.append(BorderControl(
            category=BorderControlCategory.SPS,
            code="CHED-P",
            title=Bilingual(
                "Certificado fitosanitario (CHED-P) y control en puesto fronterizo",
                "Phytosanitary certificate (CHED-P) and border control post check",
            ).text(language),
            authority="PCF",
            requirement=Bilingual(
                "Los productos de origen vegetal están sujetos a control "
                "fitosanitario en un puesto de control fronterizo: se exige CHED-P "
                "emitido por la autoridad competente del país de origen.",
                "Products of plant origin are subject to phytosanitary checks at a "
                "border control post: a CHED-P issued by the competent authority of "
                "the country of origin is required.",
            ).text(language),
            mandatory=True,
            source=DataSource.KNOWLEDGE_BASE,
        ))

    if country.upper() == "ES" and _matches(SOIVRE_PREFIXES, taric_code):
        controls.append(BorderControl(
            category=BorderControlCategory.TBT,
            code="SOIVRE",
            title=Bilingual(
                "Control de seguridad industrial por SOIVRE",
                "Industrial product safety control by SOIVRE",
            ).text(language),
            authority="SOIVRE",
            requirement=Bilingual(
                "Los productos industriales de los sectores regulados (productos "
                "químicos, textiles, calzado, juguetes, maquinaria, vehículos y "
                "equipos eléctricos) requieren declaración responsable y control de "
                "seguridad industrial en la puesta en el mercado.",
                "Industrial products in regulated sectors (chemicals, textiles, "
                "footwear, toys, machinery, vehicles and electrical equipment) require "
                "a responsible declaration and industrial safety control before being "
                "placed on the market.",
            ).text(language),
            mandatory=True,
            source=DataSource.KNOWLEDGE_BASE,
        ))
    return controls


def is_sanctioned_country(country: str) -> bool:
    return country.upper() in {"RU", "BY", "IR", "KP", "SY"}
