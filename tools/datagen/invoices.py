"""Construcción de la factura completa (datos, no presentación).

Cada factura se genera con un arquetipo:

* ``EXTRA_EU`` — proveedor de fuera de la UE, comprador español, factura en
  inglés (mayoría) o español, Incoterm, flete/seguro, bultos, peso, B/L o AWB.
* ``INTRA_EU`` — proveedor de otro Estado miembro, comprador español, IVA 0 %
  por inversión del sujeto pasivo.
* ``DOMESTIC`` — proveedor español, comprador español, IVA español y, en parte,
  QR de la AEAT (RD 1619/2012 art. 6.5).
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

import parties
from products import Catalog, Line, build_lines

ARCHETYPE_WEIGHTS = (("EXTRA_EU", 55), ("INTRA_EU", 30), ("DOMESTIC", 15))

_EXTRA_COUNTRIES = [
    ("CN", 38), ("IN", 12), ("TR", 10), ("US", 9), ("VN", 8), ("GB", 6),
    ("BD", 4), ("PK", 4), ("MA", 3), ("TW", 2), ("KR", 2), ("JP", 1), ("TH", 1),
]
_INTRA_COUNTRIES = [("DE", 26), ("FR", 20), ("IT", 22), ("PT", 17), ("NL", 8), ("PL", 5), ("BE", 2)]

_FX = {"EUR": 1.0, "USD": 1.09, "GBP": 0.85, "CNY": 7.75, "JPY": 163.0}

_CURRENCY_BY_COUNTRY = {
    "CN": ("USD", "CNY"), "US": ("USD",), "IN": ("USD", "EUR"), "TR": ("EUR", "USD"),
    "GB": ("GBP", "EUR"), "JP": ("JPY", "USD"), "KR": ("USD",), "TW": ("USD",),
    "VN": ("USD",), "BD": ("USD",), "PK": ("USD",), "MA": ("EUR",), "TH": ("USD",),
    "DE": ("EUR",), "FR": ("EUR",), "IT": ("EUR",), "PT": ("EUR",), "NL": ("EUR",),
    "PL": ("EUR",), "BE": ("EUR",), "ES": ("EUR",),
}

_INCOTERMS_SEA = [("CIF", 42), ("FOB", 30), ("CFR", 12), ("FCA", 9), ("EXW", 7)]
_INCOTERMS_AIR = [("CPT", 35), ("FCA", 30), ("CIP", 20), ("EXW", 15)]
_INCOTERMS_INTRA = [("DAP", 40), ("FCA", 30), ("EXW", 15), ("DDP", 15)]
_INCOTERMS_DOMESTIC = [("PORTES PAGADOS", 45), ("EXW", 20), ("DAP", 35)]

def _incoterm_place(
    rng: random.Random,
    incoterm: str,
    archetype: str,
    supplier: parties.Party,
    buyer: parties.Party,
    country: str,
) -> str:
    if incoterm in {"FCA", "EXW"}:
        return supplier.city
    if incoterm == "FOB":
        routes = parties.SEA_ROUTES.get(country) or []
        return routes[0][0] if routes else supplier.city
    if incoterm in {"CIF", "CFR"}:
        if archetype == "INTRA_EU":
            return buyer.city
        return rng.choice(("Valencia", "Barcelona", "Algeciras", "Bilbao"))
    if incoterm in {"CPT", "CIP"}:
        return rng.choice(("Madrid-Barajas", "Barcelona-El Prat", "Valencia"))
    return buyer.city


_SERIES = {
    "CN": ["CI-2026-####", "INV-26-#####", "SALES-2026-####"],
    "IN": ["EXP/2026/####", "INV-2026-#####"],
    "TR": ["FT-2026/#####", "EXW-2026-####"],
    "US": ["INV-2026-#####", "SI-26-####"],
    "GB": ["INV-2026-####", "GB/2026/####"],
    "VN": ["VN-2026/####", "INV-26-#####"],
    "IN_DEFAULT": ["INV-2026-#####", "EXP-2026-####"],
    "DE": ["RE-2026-#####", "2026-####"],
    "FR": ["2026/#####", "FC-2026-####"],
    "IT": ["FT 2026/#####", "2026/####"],
    "PT": ["FT 2026/####", "2026/FT/####"],
    "NL": ["2026-####", "INV-2026-####"],
    "PL": ["FV/2026/####", "2026/####"],
    "BE": ["2026/####", "FAC-2026-####"],
    "ES": ["F2026/#####", "2026/#####", "FA-2026-####"],
}

_VAT_BY_CHAPTER = {
    "49": 4, "03": 10, "07": 10, "08": 10, "10": 10, "16": 10, "17": 10, "19": 10,
    "20": 10, "21": 10, "22": 21,
}

_TOTAL_LABELS = {
    "en": {"goods": "Goods value", "discount": "Discount", "freight": "Freight",
           "insurance": "Insurance", "other": "Other charges", "base": "Taxable amount",
           "vat": "VAT", "total": "TOTAL", "words": "Say"},
    "es": {"goods": "Base imponible (mercancías)", "discount": "Descuento",
           "freight": "Transporte", "insurance": "Seguro", "other": "Otros gastos",
           "base": "Base imponible", "vat": "IVA", "total": "TOTAL", "words": "Son"},
}


@dataclass
class Invoice:
    doc_id: str
    archetype: str
    language: str
    layout: str
    number: str
    issue_date: dt.date
    supply_date: dt.date
    due_date: dt.date
    supplier: parties.Party
    buyer: parties.Party
    currency: str
    fx_rate: float
    incoterm: str
    incoterm_place: str
    lines: list[Line]
    goods_amount: float
    discount_pct: float
    discount: float
    freight: float
    insurance: float
    other_costs: float
    taxable_base: float
    vat_breakdown: list[dict]
    vat_amount: float
    total: float
    total_eur: float
    payment_terms: str
    transport: dict
    reference: str
    customer_ref: str
    notes: list[str]
    qr: str | None
    scan: bool
    scanned_angle: float
    pages: int
    correction: dict | None
    edge_case: str | None
    vat_label: str
    bank_details: dict
    totals_labels: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "archetype": self.archetype,
            "language": self.language,
            "layout": self.layout,
            "scan": self.scan,
            "scanned_angle": round(self.scanned_angle, 1),
            "pages": self.pages,
            "edge_case": self.edge_case,
            "invoice": {
                "number": self.number,
                "issue_date": self.issue_date.isoformat(),
                "supply_date": self.supply_date.isoformat(),
                "due_date": self.due_date.isoformat(),
                "currency": self.currency,
                "fx_rate_eur": self.fx_rate,
                "incoterm": self.incoterm,
                "incoterm_place": self.incoterm_place,
                "payment_terms": self.payment_terms,
                "supplier_reference": self.reference,
                "customer_reference": self.customer_ref,
                "correction": self.correction,
            },
            "supplier": _party_dict(self.supplier),
            "buyer": _party_dict(self.buyer),
            "transport": self.transport,
            "lines": [line.as_dict() for line in self.lines],
            "totals": {
                "goods_amount": self.goods_amount,
                "discount_pct": self.discount_pct,
                "discount": self.discount,
                "freight": self.freight,
                "insurance": self.insurance,
                "other_costs": self.other_costs,
                "taxable_base": self.taxable_base,
                "vat": self.vat_breakdown,
                "vat_amount": self.vat_amount,
                "total": self.total,
                "total_eur": self.total_eur,
                "total_in_words": self.words,
            },
            "customs": {
                "eori_importer": self.buyer.eori,
                "incoterm": self.incoterm,
                "incoterm_place": self.incoterm_place,
                "currency": self.currency,
                "fx_rate_eur": self.fx_rate,
            },
            "qr": self.qr,
            "review": {"status": "pending_review", "reviewed_by": None, "reviewed_at": None,
                       "errors": [], "notes": ""},
        }

    @property
    def words(self) -> str:
        fn = parties.amount_in_words_es if self.language == "es" else parties.amount_in_words_en
        return fn(abs(self.total), self.currency)


def _party_dict(party: parties.Party) -> dict:
    return {
        "name": party.name, "address": party.address, "city": party.city,
        "postcode": party.postcode, "country": party.country,
        "tax_id": party.tax_id, "tax_label": party.tax_label, "eori": party.eori,
        "contact": party.contact, "phone": party.phone, "email": party.email,
    }


def _weighted(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def _number(rng: random.Random, country: str, used: set[str]) -> str:
    series = _SERIES.get(country, _SERIES["IN_DEFAULT"])
    template = rng.choice(series)
    for _ in range(200):
        out = []
        for ch in template:
            out.append(str(rng.randint(0, 9)) if ch == "#" else ch)
        number = "".join(out)
        if number not in used:
            used.add(number)
            return number
    raise RuntimeError("no se pudo generar un número de factura único")


def _business_day(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    while True:
        day = start + dt.timedelta(days=rng.randint(0, (end - start).days))
        if day.weekday() < 5:
            return day


def _line_count(rng: random.Random) -> int:
    roll = rng.random()
    if roll < 0.16:
        return rng.choice((1, 1, 2))
    if roll < 0.54:
        return rng.randint(3, 7)
    if roll < 0.82:
        return rng.randint(8, 14)
    if roll < 0.95:
        return rng.randint(15, 24)
    return rng.randint(25, 34)


def _transport(
    rng: random.Random,
    archetype: str,
    supplier: parties.Party,
    buyer: parties.Party,
    gross_total: float,
    incoterm: str,
) -> tuple[dict, float, float]:
    """Devuelve (datos de transporte, flete facturado, seguro facturado)."""
    if archetype == "EXTRA_EU":
        mode = "sea" if gross_total > 900 or rng.random() < 0.68 else "air"
    elif archetype == "INTRA_EU":
        mode = "road" if rng.random() < 0.78 else ("sea" if rng.random() < 0.5 else "air")
    else:
        mode = "road"

    freight = 0.0
    insurance = 0.0
    if mode == "sea":
        route = rng.choice(parties.SEA_ROUTES.get(supplier.country) or [(supplier.city, "Valencia", 5)])
        vessel, voyage = rng.choice(parties.VESSELS)
        data = {
            "mode": "sea",
            "origin_port": route[0],
            "destination_port": route[1],
            "transit_days": route[2],
            "vessel": vessel,
            "voyage": voyage,
            "carrier": rng.choice(parties.SHIP_LINES),
            "bl_number": rng.choice(("MEDU", "COSU", "MSCU", "HLCU", "ONEY")) + f"{rng.randint(1000000, 9999999)}",
            "container": parties.container(rng, rng.choice(("MSCU", "CMAU", "HLXU", "TGHU", "OOLU", "TRLU"))),
            "seal": f"{rng.choice(('ES', 'ML', 'CN'))}{rng.randint(100000, 999999)}",
            "packages": 0,
            "gross_weight": round(gross_total, 2),
            "customs_office": parties.CUSTOMS_OFFICES.get(buyer.city, "ES002001"),
        }
        if incoterm in {"CIF", "CFR", "CPT", "CIP", "DAP", "DDP"}:
            freight = round(max(180.0, gross_total * rng.uniform(0.28, 0.85)), 2)
        if incoterm in {"CIF", "CIP"}:
            insurance = round(max(25.0, gross_total * rng.uniform(0.003, 0.006)), 2)
    elif mode == "air":
        if supplier.country in parties.EU_AIRPORTS:
            origins = parties.EU_AIRPORTS[supplier.country]
        else:
            origins = parties.EXTRA_AIRPORTS.get(supplier.country, ("HKG",))
        data = {
            "mode": "air",
            "origin_airport": rng.choice(origins),
            "destination_airport": rng.choice(parties.SPANISH_AIRPORTS),
            "carrier": rng.choice(("Iberia Cargo", "Air Europa Cargo", "Lufthansa Cargo", "Emirates SkyCargo")),
            "awb": f"{rng.choice((75, 125, 160, 176, 996))}-{rng.randint(10000000, 99999999)}",
            "pieces": 0,
            "gross_weight": round(gross_total, 2),
            "customs_office": parties.CUSTOMS_OFFICES.get(buyer.city, "ES002007"),
        }
        if incoterm in {"CIF", "CFR", "CPT", "CIP", "DAP", "DDP"}:
            freight = round(max(120.0, gross_total * rng.uniform(2.2, 4.8)), 2)
        if incoterm in {"CIF", "CIP"}:
            insurance = round(max(20.0, gross_total * rng.uniform(0.004, 0.008)), 2)
    else:
        data = {
            "mode": "road",
            "cmr_number": f"CMR-{rng.randint(100000, 999999)}",
            "carrier": rng.choice(("Translevante", "EuroRoad Cargo", "Iberia Frío", "NordSud Transportes")),
            "truck_plate": f"{rng.randint(1000, 9999)}-{''.join(rng.choice('BCDFGHJKLMNPRSTVWXYZ') for _ in range(3))}",
            "route": f"{supplier.city} – {buyer.city}",
            "packages": 0,
            "gross_weight": round(gross_total, 2),
            "customs_office": parties.CUSTOMS_OFFICES.get(buyer.city, "ES002001"),
        }
        if incoterm in {"DAP", "DDP", "PORTES PAGADOS"}:
            freight = round(max(45.0, gross_total * rng.uniform(0.05, 0.14)), 2)
    return data, freight, insurance


def _notes(rng: random.Random, inv_lang: str, archetype: str, incoterm: str,
           supplier: parties.Party, buyer: parties.Party, vat_rate: float) -> list[str]:
    if inv_lang == "en":
        notes = []
        if archetype == "EXTRA_EU":
            notes.append("Country of origin of the goods: as stated per line.")
            notes.append("The exporter hereby certifies that the goods described in this invoice are of the stated origin.")
            if incoterm in {"FOB", "CFR", "CIF"}:
                notes.append(f"Shipment under {incoterm} terms. Freight and insurance as per contract.")
            notes.append("Import VAT and customs duties are payable by the importer in Spain.")
            if rng.random() < 0.5:
                notes.append("Please state the invoice number in all bank transfers.")
        elif archetype == "INTRA_EU":
            notes.append("Intra-EU supply of goods. VAT exempt under Article 138 of Directive 2006/112/EC.")
            notes.append("Reverse charge: VAT to be accounted for by the recipient (Article 196 of Directive 2006/112/EC).")
            if rng.random() < 0.4:
                notes.append("Delivery under the intra-EU VIES regime. Customer VAT number validated.")
        else:
            notes.append("Supply of goods. VAT charged at the rates shown.")
        if rng.random() < 0.3:
            notes.append(f"EORI number of the importer: {buyer.eori}.")
        return notes

    notes = []
    if archetype == "EXTRA_EU":
        notes.append("Mercancía de origen según se indica en cada línea.")
        notes.append("El exportador certifica que la mercancía descrita corresponde a la origen declarada.")
        notes.append("El IVA y los derechos de aduana a la importación son a cargo del importador.")
        if rng.random() < 0.4:
            notes.append("Rogamos citen el número de factura en todas las transferencias.")
    elif archetype == "INTRA_EU":
        notes.append("Entrega intracomunitaria de bienes exenta del IVA (art. 138 Directiva 2006/112/CE).")
        notes.append("Inversión del sujeto pasivo: el destinatario autoliquida el IVA (art. 196 Directiva 2006/112/CE).")
        if rng.random() < 0.4:
            notes.append("Operación amparada por el régimen de inversión del sujeto pasivo (art. 84.Uno.2.º LIVA).")
    else:
        notes.append("Factura sujeta a IVA. Operación incluida en los libros registro de facturas expedidas y recibidas.")
        if vat_rate == 0:
            notes.append("Operación exenta de IVA.")
    if rng.random() < 0.25:
        notes.append(f"EORI del importador: {buyer.eori}.")
    return notes


def _vat_rate(rng: random.Random, chapter: str, single_rate: bool) -> int:
    if single_rate:
        return 21 if chapter not in {"03", "07", "08", "20", "21"} else 10
    return _VAT_BY_CHAPTER.get(chapter, 21)


def _qr_payload(number: str, issue: dt.date, supplier: parties.Party, total: float) -> str:
    return (
        "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?"
        f"nif={supplier.tax_id}&numserie={number.replace(' ', '').replace('/', '-')}"
        f"&fecha={issue.strftime('%d-%m-%Y')}&importe={total:.2f}"
    )


_CN_SWIFT = {
    "Ningbo Commercial Bank": "NBCBCN2N",
    "Pearl River Bank": "PRBKCN2N",
    "East Asia Trade Bank": "EATBCN2N",
    "China Meridian Bank": "CMBKCN2N",
    "Harbour Savings Bank": "HSBKCN2N",
}


def _bank_details(supplier: parties.Party) -> dict:
    if supplier.country == "CN":
        return {
            "beneficiary": supplier.name,
            "bank": supplier.bank_name,
            "account": rng_digits(supplier.tax_id),
            "swift": _CN_SWIFT.get(supplier.bank_name or "", "NBCBCN2N"),
            "iban": "",
        }
    account = supplier.iban or ""
    # Fuera del SEPA no hay IBAN: la transferencia va con cuenta local y SWIFT.
    return {
        "beneficiary": supplier.name,
        "bank": supplier.bank_name or "",
        "account": "" if account else rng_digits(supplier.tax_id or supplier.name),
        "swift": supplier.bic or "",
        "iban": account,
    }


def rng_digits(seed_text: str) -> str:
    value = sum(ord(ch) * (i + 3) for i, ch in enumerate(seed_text))
    base = (value * 7919) % 10**12
    return f"{base:012d}"


def build_invoice(
    rng: random.Random,
    doc_id: str,
    catalog: Catalog,
    archetype: str,
    language: str | None,
    layout: str,
    used_numbers: set[str],
    used_suppliers: set[str],
    used_buyers: set[str],
    edge_case: str | None = None,
) -> Invoice:
    if archetype == "EXTRA_EU":
        country = _weighted(rng, _EXTRA_COUNTRIES)
    elif archetype == "INTRA_EU":
        country = _weighted(rng, _INTRA_COUNTRIES)
    else:
        country = "ES"

    if language is None:
        if archetype == "DOMESTIC":
            language = "es"
        elif archetype == "EXTRA_EU":
            language = "es" if country in {"MA", "MX"} and rng.random() < 0.6 else "en"
        else:
            language = "es" if rng.random() < 0.55 else "en"

    supplier = parties.make_supplier(rng, country, used_suppliers)
    buyer = parties.make_buyer(rng, used_buyers)

    issue_date = _business_day(rng, dt.date(2025, 9, 1), dt.date(2026, 11, 13))
    supply_date = issue_date - dt.timedelta(days=rng.randint(0, 4))
    terms_pool = parties.PAYMENT_TERMS_ES if language == "es" else parties.PAYMENT_TERMS_EN
    payment_terms, payment_days = rng.choice(terms_pool)
    due_date = issue_date + dt.timedelta(days=payment_days)

    if archetype == "EXTRA_EU":
        incoterm = _weighted(rng, _INCOTERMS_SEA if rng.random() < 0.72 else _INCOTERMS_AIR)
    elif archetype == "INTRA_EU":
        incoterm = _weighted(rng, _INCOTERMS_INTRA)
    else:
        incoterm = _weighted(rng, _INCOTERMS_DOMESTIC)
    incoterm_place = _incoterm_place(rng, incoterm, archetype, supplier, buyer, country)

    currency = rng.choice(_CURRENCY_BY_COUNTRY[country])
    base_fx = _FX[currency]
    fx = 1.0 if currency == "EUR" else round(base_fx * rng.uniform(0.975, 1.025), 4)

    discount_pct = 0.0
    if rng.random() < 0.22:
        discount_pct = rng.choice((1.0, 2.0, 2.5, 3.0, 5.0))

    count = _line_count(rng)
    if edge_case == "single_line":
        count = 1
    elif edge_case == "many_lines":
        count = rng.randint(26, 34)

    lines = build_lines(rng, catalog, archetype, language, country, count, fx, currency)
    if not lines:
        raise RuntimeError("sin líneas")
    for i, line in enumerate(lines, start=1):
        line.line_no = i

    if edge_case == "credit_note":
        for line in lines:
            line.quantity = -line.quantity
            line.amount = -line.amount

    goods = round(sum(line.amount for line in lines), 2)
    discount = round(goods * discount_pct / 100, 2)
    net = goods - discount

    gross_weight = round(sum(line.gross_weight for line in lines), 2)
    transport, freight, insurance = _transport(
        rng, archetype, supplier, buyer, gross_weight, incoterm
    )
    transport["packages"] = sum(line.packages for line in lines)
    other = 0.0
    if archetype != "EXTRA_EU" and rng.random() < 0.12:
        other = round(rng.uniform(15, 80), 2)

    if edge_case == "credit_note":
        freight = -abs(freight) if freight else 0.0
        insurance = -abs(insurance) if insurance else 0.0
        other = -abs(other) if other else 0.0

    base = round(net + freight + insurance + other, 2)

    single_rate = rng.random() < 0.65
    vat_groups: dict[int, float] = {}
    if archetype == "DOMESTIC":
        for line in lines:
            rate = _vat_rate(rng, line.cn8[:2], single_rate)
            vat_groups[rate] = round(vat_groups.get(rate, 0.0) + line.amount, 2)
        if discount:
            for rate in vat_groups:
                vat_groups[rate] = round(vat_groups[rate] * (1 - discount_pct / 100), 2)
        # Reparto del resto de gastos en el grupo de tipo más alto.
        if freight or insurance or other:
            top = max(vat_groups)
            vat_groups[top] = round(vat_groups[top] + freight + insurance + other, 2)
    else:
        vat_groups = {0: base}

    vat_breakdown = []
    vat_amount = 0.0
    for rate in sorted(vat_groups):
        group_base = round(vat_groups[rate], 2)
        group_vat = round(group_base * rate / 100, 2)
        vat_breakdown.append({"rate": rate, "base": group_base, "amount": group_vat})
        vat_amount += group_vat
    vat_amount = round(vat_amount, 2)
    total = round(base + vat_amount, 2)

    vat_label = {
        0: "0 % (importación)" if archetype == "EXTRA_EU" else "0 % (ISP)",
        4: "4 %", 10: "10 %", 21: "21 %",
    }.get(vat_breakdown[0]["rate"] if len(vat_breakdown) == 1 else -1, "varios tipos")

    number = _number(rng, country, used_numbers)
    ref_prefix = rng.choice(("PEDIDO", "REF")) if language == "es" else rng.choice(("PO", "ORDER", "SC"))
    reference = f"{ref_prefix}-{issue_date.year}-{rng.randint(1000, 9999)}"
    customer_ref = f"{rng.choice(('REF', 'PO', 'PEDIDO'))} {buyer.tax_id[:4]}-{rng.randint(100, 999)}"

    correction = None
    if edge_case == "credit_note":
        correction = {
            "original_number": _number(rng, country, used_numbers),
            "original_date": (issue_date - dt.timedelta(days=rng.randint(20, 90))).isoformat(),
            "reason": "Devolución de mercancía" if language == "es" else "Returned goods",
        }

    qr = None
    if archetype == "DOMESTIC" and edge_case != "credit_note" and rng.random() < 0.45:
        qr = _qr_payload(number, issue_date, supplier, total)

    notes = _notes(rng, language, archetype, incoterm, supplier, buyer,
                   vat_breakdown[0]["rate"] if vat_breakdown else 0)

    scan = (language == "en" and rng.random() < 0.16) or (language == "es" and rng.random() < 0.06)

    return Invoice(
        doc_id=doc_id,
        archetype=archetype,
        language=language,
        layout=layout,
        number=number,
        issue_date=issue_date,
        supply_date=supply_date,
        due_date=due_date,
        supplier=supplier,
        buyer=buyer,
        currency=currency,
        fx_rate=fx,
        incoterm=incoterm,
        incoterm_place=incoterm_place,
        lines=lines,
        goods_amount=goods,
        discount_pct=discount_pct,
        discount=discount,
        freight=freight,
        insurance=insurance,
        other_costs=other,
        taxable_base=base,
        vat_breakdown=vat_breakdown,
        vat_amount=vat_amount,
        total=total,
        total_eur=round(total / fx, 2),
        payment_terms=payment_terms,
        transport=transport,
        reference=reference,
        customer_ref=customer_ref,
        notes=notes,
        qr=qr,
        scan=scan,
        scanned_angle=rng.uniform(-1.2, 1.2) if scan else 0.0,
        pages=1,
        correction=correction,
        edge_case=edge_case,
        vat_label=vat_label,
        bank_details=_bank_details(supplier),
        totals_labels=_TOTAL_LABELS[language],
    )
