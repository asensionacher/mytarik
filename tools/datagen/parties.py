"""Partes, identificadores y datos de transporte ficticios pero coherentes.

Reglas duras:

* Ningún nombre de empresa o marca real (lista de bloqueo al final).
* NIF/CIF español con dígito de control correcto (algoritmo AEAT).
* NIF-IVA de DE/FR/IT/NL/PT/PL/BE/GB con su dígito de control.
* IBAN con mod-97 correcto y BIC con estructura válida, de bancos inventados.
* USCI china de 18 caracteres con control base 31 (GB 32100-2015).
* Contenedores ISO 6346 con dígito de control.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field

# ── Identificadores ──────────────────────────────────────────────────────

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_LETTERS = "JABCDEFGHI"
_USCI_ALPHABET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCI_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def dni_nif(rng: random.Random) -> str:
    number = rng.randint(10_000_000, 99_999_999)
    return f"{number}{_DNI_LETTERS[number % 23]}"


def company_nif(rng: random.Random, prefix: str | None = None) -> str:
    prefix = prefix or rng.choice("ABCDEFGHJNPQRSUVW")
    digits = [rng.randint(0, 9) for _ in range(7)]
    total = 0
    for i, digit in enumerate(digits, start=1):
        if i % 2 == 1:
            doubled = digit * 2
            total += doubled // 10 + doubled % 10
        else:
            total += digit
    control = (10 - total % 10) % 10
    if prefix in "KPQSNW":
        return f"{prefix}{''.join(map(str, digits))}{_CIF_LETTERS[control]}"
    if prefix in "ABEH":
        return f"{prefix}{''.join(map(str, digits))}{control}"
    return f"{prefix}{''.join(map(str, digits))}{control if rng.random() < 0.5 else _CIF_LETTERS[control]}"


def check_nif(value: str) -> bool:
    value = value.strip().upper()
    if re.fullmatch(r"\d{8}[A-Z]", value):
        return _DNI_LETTERS[int(value[:8]) % 23] == value[8]
    if re.fullmatch(r"[A-Z]\d{7}[0-9A-Z]", value):
        prefix, digits, control = value[0], value[1:8], value[8]
        total = 0
        for i, digit in enumerate(digits, start=1):
            d = int(digit)
            if i % 2 == 1:
                doubled = d * 2
                total += doubled // 10 + doubled % 10
            else:
                total += d
        expected = (10 - total % 10) % 10
        return control == str(expected) or control == _CIF_LETTERS[expected]
    return False


def eori(country: str, identifier: str) -> str:
    return f"{country}{identifier}"


def iban(country: str, bbans: dict[str, int], rng: random.Random) -> str:
    """IBAN con dígitos de control mod-97 correctos."""
    length = bbans[country]
    bban = "".join(str(rng.randint(0, 9)) for _ in range(length - 4))
    numeric = bban + country + "00"
    converted = "".join(str(int(ch)) if ch.isdigit() else str(ord(ch) - 55) for ch in numeric)
    check = 98 - int(converted) % 97
    return f"{country}{check:02d}{bban}"


_IBAN_LENGTHS = {"ES": 24, "DE": 22, "FR": 27, "IT": 27, "PT": 25, "NL": 18, "PL": 28,
                 "BE": 16, "GB": 22}


def check_iban(value: str) -> bool:
    value = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", value):
        return False
    if value[:2] in _IBAN_LENGTHS and len(value) != _IBAN_LENGTHS[value[:2]]:
        return False
    moved = value[4:] + value[:4]
    converted = "".join(str(int(ch)) if ch.isdigit() else str(ord(ch) - 55) for ch in moved)
    return int(converted) % 97 == 1


def bic(rng: random.Random, country: str) -> str:
    bank = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4))
    location = f"{rng.randint(10, 99)}{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"
    return f"{bank}{country}{location}{'XXX' if rng.random() < 0.35 else ''}"


def usci(rng: random.Random, region: str = "3302") -> str:
    """Código unificado social de crédito (18 caracteres, control base 31)."""
    body = rng.choice("159Y") + rng.choice("123456789") + f"{region}{rng.randint(0, 99):02d}"
    body += "".join(rng.choice(_USCI_ALPHABET) for _ in range(9))
    total = sum(_USCI_ALPHABET.index(ch) * w for ch, w in zip(body, _USCI_WEIGHTS))
    check = (31 - total % 31) % 31
    return body + _USCI_ALPHABET[check]


def check_usci(value: str) -> bool:
    if len(value) != 18 or any(ch not in _USCI_ALPHABET for ch in value):
        return False
    total = sum(_USCI_ALPHABET.index(ch) * w for ch, w in zip(value[:17], _USCI_WEIGHTS))
    return _USCI_ALPHABET[(31 - total % 31) % 31] == value[17]


def de_vat(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(8)]
    product = 10
    for digit in digits:
        product = (digit + product) % 10
        if product == 0:
            product = 10
        product = (2 * product) % 11
    check = 11 - product
    if check == 10:
        check = 0
    return "DE" + "".join(map(str, digits)) + str(check)


def fr_vat(rng: random.Random) -> str:
    siren = [rng.randint(0, 9) for _ in range(9)]
    # Luhn sobre SIREN
    total = 0
    for i, digit in enumerate(reversed(siren)):
        if i % 2 == 1:
            doubled = digit * 2
            total += doubled // 10 + doubled % 10
        else:
            total += digit
    siren[-1] = (10 - total % 10) % 10
    number = int("".join(map(str, siren)))
    key = (12 + 3 * (number % 97)) % 97
    return f"FR{key:02d}{number}"


def it_vat(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(10)]
    province = rng.choice(("201", "101", "301", "401", "501", "251"))
    body = "".join(map(str, digits)) + province
    total = 0
    for i, ch in enumerate(body):
        digit = int(ch)
        if i % 2 == 0:
            total += digit
        else:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
    check = (10 - total % 10) % 10
    return "IT" + body + str(check)


def nl_vat(rng: random.Random) -> str:
    while True:
        digits = [rng.randint(0, 9) for _ in range(8)]
        total = sum(d * w for d, w in zip(digits, (9, 8, 7, 6, 5, 4, 3, 2)))
        remainder = total % 11
        check = remainder
        if check < 10:
            digits.append(check)
            return "NL" + "".join(map(str, digits)) + "B" + f"{rng.randint(0, 99):02d}"


def pt_vat(rng: random.Random) -> str:
    digits = [rng.choice((1, 2, 3, 5, 6, 7, 8, 9))] + [rng.randint(0, 9) for _ in range(7)]
    total = sum(d * w for d, w in zip(digits, (9, 8, 7, 6, 5, 4, 3, 2)))
    check = 11 - total % 11
    if check >= 10:
        check = 0
    return "PT" + "".join(map(str, digits)) + str(check)


def pl_vat(rng: random.Random) -> str:
    while True:
        digits = [rng.randint(0, 9) for _ in range(9)]
        total = sum(d * w for d, w in zip(digits, (6, 5, 7, 2, 3, 4, 5, 6, 7)))
        check = total % 11
        if check != 10:
            return "PL" + "".join(map(str, digits)) + str(check)


def be_vat(rng: random.Random) -> str:
    base = rng.randint(10_000_000, 79_999_999)
    check = 97 - base % 97
    if check == 0:
        check = 97
    return f"BE0{base}{check:02d}"


def gb_vat(rng: random.Random) -> str:
    digits = [rng.randint(0, 9) for _ in range(7)]
    total = sum(d * w for d, w in zip(digits, (8, 7, 6, 5, 4, 3, 2)))
    check = (97 - total % 97) % 97
    return "GB" + "".join(map(str, digits)) + f"{check:02d}{rng.randint(0, 99):02d}"


def gstin(rng: random.Random) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    state = rng.choice(("27", "07", "29", "33", "19", "24"))
    pan = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(5))
    pan += f"{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
    entity = str(rng.randint(1, 9))
    body = state + pan + entity
    total = 0
    for i, ch in enumerate(body):
        value = chars.index(ch) * (2 if i % 2 else 1)
        total += value // 36 + value % 36
    return body + chars[(36 - total % 36) % 36] + "Z"


def cnpj(rng: random.Random) -> str:
    def digit(nums: list[int], weights: list[int]) -> int:
        total = sum(n * w for n, w in zip(nums, weights))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    nums = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    d1 = digit(nums, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digit(nums + [d1], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    raw = "".join(map(str, nums + [d1, d2]))
    return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"


def container(rng: random.Random, owner: str) -> str:
    values = {ch: 10 + i for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
    # ISO 6346: se omiten los valores múltiplos de 11
    value_map = {}
    counter = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        while counter % 11 == 0:
            counter += 1
        value_map[ch] = counter
        counter += 1
    digits = [rng.randint(0, 9) for _ in range(6)]
    total = sum(value_map[ch] * (2**i) for i, ch in enumerate(owner)) + sum(
        d * (2**i) for i, d in enumerate(digits, start=4)
    )
    check = total % 11
    if check == 10:
        check = 0
    return f"{owner} {''.join(map(str, digits))} {check}"


# ── Importes en letra ────────────────────────────────────────────────────

_ES_UNITS = ("CERO", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE",
             "DIECIOCHO", "DIECINUEVE", "VEINTE")
_ES_TENS = {3: "TREINTA", 4: "CUARENTA", 5: "CINCUENTA", 6: "SESENTA", 7: "SETENTA",
            8: "OCHENTA", 9: "NOVENTA"}
_ES_HUNDREDS = {1: "CIENTO", 2: "DOSCIENTOS", 3: "TRESCIENTOS", 4: "CUATROCIENTOS",
                5: "QUINIENTOS", 6: "SEISCIENTOS", 7: "SETECIENTOS", 8: "OCHOCIENTOS",
                9: "NOVECIENTOS"}


_ES_TWENTIES = ("VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO",
                "VEINTISÉIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE")


def _es_below_1000(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    parts: list[str] = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(_ES_HUNDREDS[hundreds])
    if rest:
        if rest <= 20:
            parts.append(_ES_UNITS[rest])
        elif rest < 30:
            parts.append(_ES_TWENTIES[rest - 21])
        else:
            tens, unit = divmod(rest, 10)
            piece = _ES_TENS[tens]
            if unit:
                piece += " Y " + _ES_UNITS[unit]
            parts.append(piece)
    return " ".join(parts)


def amount_in_words_es(amount: float, currency: str = "EUR") -> str:
    cents_total = int(round(amount * 100))
    whole, cents = divmod(cents_total, 100)
    millions, remainder = divmod(whole, 1_000_000)
    thousands, units = divmod(remainder, 1000)
    words: list[str] = []
    if millions:
        words.append("UN MILLÓN" if millions == 1 else f"{_es_below_1000(millions)} MILLONES")
    if thousands:
        words.append("MIL" if thousands == 1 else f"{_es_below_1000(thousands)} MIL")
    if units:
        words.append(_es_below_1000(units))
    text = " ".join(words) or "CERO"
    if millions and not remainder:
        # "UN MILLÓN DE EUROS", pero "UN MILLÓN QUINIENTOS MIL EUROS".
        text += " DE"
    name = {"EUR": "EUROS", "USD": "DÓLARES", "GBP": "LIBRAS ESTERLINAS", "CNY": "YUANES"}.get(
        currency, currency
    )
    if currency == "EUR" and whole == 1:
        name = "EURO"
    result = f"{text} {name}"
    if cents:
        cent_name = "CÉNTIMOS" if currency == "EUR" else "CENTAVOS"
        result += f" CON {_es_below_1000(cents)} {cent_name}"
    return result


_EN_ONES = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
            "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN",
            "SEVENTEEN", "EIGHTEEN", "NINETEEN")
_EN_TENS = ("", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY")


def _en_below_1000(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _EN_TENS[tens] + (f"-{_EN_ONES[unit]}" if unit else "")
    hundreds, rest = divmod(n, 100)
    out = f"{_EN_ONES[hundreds]} HUNDRED"
    if rest:
        out += f" AND {_en_below_1000(rest)}"
    return out


def amount_in_words_en(amount: float, currency: str = "EUR") -> str:
    cents_total = int(round(amount * 100))
    whole, cents = divmod(cents_total, 100)
    millions, remainder = divmod(whole, 1_000_000)
    thousands, units = divmod(remainder, 1000)
    words: list[str] = []
    if millions:
        words.append(f"{_en_below_1000(millions)} MILLION")
    if thousands:
        words.append(f"{_en_below_1000(thousands)} THOUSAND")
    if units:
        words.append(_en_below_1000(units))
    text = " ".join(words) or "ZERO"
    name = {"EUR": "EUROS", "USD": "US DOLLARS", "GBP": "POUNDS STERLING", "CNY": "YUAN"}.get(
        currency, currency
    )
    result = f"{text} {name}"
    if cents:
        result += f" AND {_en_below_1000(cents)} CENTS"
    return result


# ── Catálogos ficticios ──────────────────────────────────────────────────

@dataclass
class Party:
    role: str
    name: str
    address: str
    city: str
    postcode: str
    country: str
    country_name_es: str
    country_name_en: str
    tax_id: str
    tax_label: str
    eori: str | None
    contact: str
    phone: str
    email: str
    bank_name: str | None = None
    iban: str | None = None
    bic: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


SPANISH_CITIES = [
    ("Valencia", "460", "ES002001", "ESVLC"),
    ("Barcelona", "080", "ES002003", "ESBCN"),
    ("Madrid", "280", "ES002007", "ESMAD"),
    ("Algeciras", "112", "ES002101", "ESALG"),
    ("Bilbao", "480", "ES002201", "ESBIO"),
    ("Sevilla", "410", "ES002301", "ESSEV"),
    ("Zaragoza", "500", "ES002401", "ESZAZ"),
    ("Alicante", "030", "ES002501", "ESALC"),
    ("Vigo", "362", "ES002601", "ESVGO"),
    ("Las Palmas", "350", "ES003501", "ESLPA"),
    ("Murcia", "300", "ES002701", "ESMJV"),
    ("Gijón", "332", "ES002801", "ESGIJ"),
]

SPANISH_STREETS = [
    "Calle Colón", "Avenida del Puerto", "Carrer de la Marina", "Calle Mayor",
    "Polígono Industrial Fuente del Jarro", "Avenida de Aragón", "Calle Alcalá",
    "Camino de la Alameda", "Ronda de Poniente", "Calle de la Industria",
    "Avenida de las Cortes Valencianas", "Calle Río Tajo", "Polígono Las Atalayas",
    "Calle de la Metalurgia", "Avenida Juan Carlos I", "Calle Ortega y Gasset",
]

BUYER_SECTORS_ES = [
    ("Textiles y confección", "MODA", "moda"),
    ("Distribución de alimentación", "ALIM", "alimentacion"),
    ("Componentes electrónicos", "TECH", "electronica"),
    ("Suministros industriales", "INDUS", "industrial"),
    ("Mobiliario y decoración", "HOME", "hogar"),
    ("Recambios de automoción", "AUTO", "auto"),
    ("Menaje y ferretería", "HOGAR", "ferreteria"),
    ("Productos sanitarios", "SALUD", "salud"),
    ("Material deportivo", "SPORT", "deporte"),
    ("Embalaje y papel", "PACK", "packaging"),
]

SPANISH_CITY_SUFFIX = ["Comercial", "Import", "Distribuciones", "Suministros", "Trade",
                       "Logística", "Mayorista", "Grupo", "Industrial", "Global"]

_ES_FIRST = ["Albufera", "Turía", "Marenostrum", "Levante", "Guadalmedina", "Ebro",
             "Duero", "Tajo", "Mediterránea", "Atlántica", "Ibérica", "Cantábrica",
             "Alameda", "Ribera", "Vega", "Serranía", "Mestral", "Tramontana",
             "Ponent", "Migjorn", "Aran", "Tordera", "Segura", "Júcar", "Magro",
             "Palancia", "Mijares", "Ter", "Llobregat", "Besós"]

_SUPPLIER_FIRST_CN = ["Ningbo", "Shenzhen", "Guangzhou", "Qingdao", "Yiwu", "Xiamen",
                      "Suzhou", "Wenzhou", "Hangzhou", "Dongguan", "Foshan", "Shanghai"]
_SUPPLIER_SECOND_CN = ["Haoyu", "Jinlong", "Tianhe", "Yongsheng", "Meixin", "Ruifeng",
                       "Kangda", "Xinhao", "Lianfa", "Shunyi", "Zhongtai", "Hengda",
                       "Baoyuan", "Chenxing", "Dongfang", "Fuhua", "Guoxin", "Huayuan"]
_SUPPLIER_KIND_CN = ["Trading Co., Ltd.", "Industrial Co., Ltd.", "Import & Export Co., Ltd.",
                     "Manufacturing Co., Ltd.", "Group Co., Ltd."]

_EU_SUPPLIERS = {
    "DE": ["Nordwerk", "Rheinland", "Hansa", "Elbtal", "Südwerk", "Weser"],
    "FR": ["Provence", "Atlantique", "Lorraine", "Rhône"],
    "IT": ["Lombarda", "Adriatica", "Toscana", "Veneta"],
    "PT": ["Douro", "Tejo", "Alentejo", "Minho"],
    "NL": ["Rijn", "Maas", "Flevo", "Brabant"],
    "PL": ["Wisła", "Odra", "Bałtyk", "Karpaty"],
    "BE": ["Schelde", "Meuse", "Bruxelles"],
}
_EU_CITIES = {
    "DE": [("Hamburg", "20", "DEHAM"), ("Bremen", "28", "DEBRE"), ("Düsseldorf", "40", "DEDUS"),
           ("München", "80", "DEMUC"), ("Stuttgart", "70", "DESTR")],
    "FR": [("Le Havre", "76", "FRLEH"), ("Marseille", "13", "FRMRS"), ("Lyon", "69", "FRLYS"),
           ("Bordeaux", "33", "FRBOD")],
    "IT": [("Genova", "16", "ITGOA"), ("Milano", "20", "ITMIL"), ("La Spezia", "19", "ITSPE"),
           ("Verona", "37", "ITVRN")],
    "PT": [("Porto", "40", "PTOPO"), ("Lisboa", "10", "PTLIS"), ("Leixões", "44", "PTLEI")],
    "NL": [("Rotterdam", "30", "NLRTM"), ("Amsterdam", "10", "NLAMS")],
    "PL": [("Gdansk", "80", "PLGDN"), ("Poznan", "60", "PLPOZ")],
    "BE": [("Antwerpen", "20", "BEANR")],
}
_COUNTRY_NAMES = {
    "ES": ("España", "Spain"), "DE": ("Alemania", "Germany"), "FR": ("Francia", "France"),
    "IT": ("Italia", "Italy"), "PT": ("Portugal", "Portugal"), "NL": ("Países Bajos", "Netherlands"),
    "PL": ("Polonia", "Poland"), "BE": ("Bélgica", "Belgium"), "CN": ("China", "China"),
    "US": ("Estados Unidos", "United States"), "IN": ("India", "India"),
    "TR": ("Turquía", "Türkiye"), "GB": ("Reino Unido", "United Kingdom"),
    "VN": ("Vietnam", "Vietnam"), "BR": ("Brasil", "Brazil"), "MA": ("Marruecos", "Morocco"),
    "TW": ("Taiwán", "Taiwan"), "KR": ("Corea del Sur", "South Korea"),
    "JP": ("Japón", "Japan"), "PK": ("Pakistán", "Pakistan"),
    "BD": ("Bangladesh", "Bangladesh"), "TH": ("Tailandia", "Thailand"),
    "MX": ("México", "Mexico"), "ID": ("Indonesia", "Indonesia"),
}

_EXTRA_EU_CITIES = {
    "US": [("Los Angeles, CA", "900", "USLAX"), ("Houston, TX", "770", "USHOU"),
           ("Newark, NJ", "071", "USEWR"), ("Savannah, GA", "314", "USSAV")],
    "IN": [("Mumbai", "400", "INBOM"), ("Chennai", "600", "INMAA"), ("Delhi", "110", "INDEL"),
           ("Ahmedabad", "380", "INAMD")],
    "TR": [("Istanbul", "340", "TRIST"), ("Izmir", "350", "TRIZM"), ("Bursa", "160", "TRBUR")],
    "GB": [("Felixstowe", "IP11", "GBFXT"), ("Manchester", "M1", "GBMAN"),
           ("Southampton", "SO14", "GBSOU")],
    "VN": [("Hai Phong", "180", "VNHPH"), ("Ho Chi Minh City", "700", "VNSGN")],
    "BR": [("Santos", "110", "BRSSZ"), ("São Paulo", "010", "BRSAO")],
    "MA": [("Casablanca", "200", "MACAS"), ("Tangier", "900", "MATNG")],
    "TW": [("Kaohsiung", "800", "TWKHH"), ("Taipei", "100", "TWTPE")],
    "KR": [("Busan", "480", "KRPUS"), ("Incheon", "220", "KRINC")],
    "JP": [("Yokohama", "220", "JPYOK"), ("Kobe", "650", "JPUKB")],
    "PK": [("Karachi", "740", "PKKHI")],
    "BD": [("Chittagong", "4000", "BDCGP")],
    "TH": [("Laem Chabang", "200", "THLCH")],
    "MX": [("Manzanillo", "280", "MXZLO")],
    "ID": [("Tanjung Priok", "140", "IDTPP")],
}

_BANK_STEMS = ["TREL", "ZULV", "NORB", "QARV", "VELT", "MIRD", "CALX", "PENV", "ARQV", "SOLD"]
_BANK_NAMES = ["Banco Trelvant", "Banca Zulvia", "Nordbay Bank", "Qarvia Bank",
               "Veltonia Bank", "Miranda de Crédito", "Calixa Bank", "Penvale Bank",
               "Arquía del Sur", "Soldea Bank"]

BRANDS = [
    "NORTHWIND", "VELMORA", "KAIROS", "LUMENCO", "ASTRAVIA", "BRUNEL", "SELVATICA",
    "ORVEN", "TALVERA", "MIRAVELLE", "QUANTIX", "ZENTRA", "HELIOSA", "ALTAMIRA",
    "BELKAN", "CORDOVA", "DUNMORE", "ESTRADA", "FARALLO", "GRANVIA", "HELVETIA",
    "IRONMARK", "JAVALI", "KESTREL", "LANTIA", "MONTARA", "NOVARA", "OCEANDA",
    "PALMARES", "QUIRINAL", "RIVIERA", "SABATIER", "TERRAL", "UMBRIA", "VERDANT",
    "WESTBOURNE", "XANTHE", "YARROW", "ZAFIRA", "ALCOR", "BOREAL", "CIMBRA",
    "DELFOS", "ELARA", "FULGOR", "GAUDIA", "HALCON", "ITACA", "JUNCO", "KANTA",
    "LUMBRE", "MAREA", "NEREIDA", "OLIVA", "PAMPERO", "QUETZAL", "REBALSA",
    "SIROCCO", "TEMPESTA", "URANIA", "VALIRA", "WINDFALL", "XENIA", "YUNQUE",
    "ZORZAL", "ARDORA", "BRUMA", "CEIBA", "DRAGA", "ESPIGA", "FARO", "GRÉGAL",
    "HIDRA", "ÍTACA", "JADE", "KELPIE", "LAGO", "MAGMA", "NÍVEO", "OROPEL",
]

_COMPANY_BLOCKLIST = (
    "inditex", "zara", "mango", "mercadona", "telefonica", "iberdrola", "repsol",
    "santander", "bbva", "caixabank", "el corte ingles", "sepi", "casa tarradellas",
    "campofrio", "freixenet", "codorniu", "loewe", "camper", "desigual", "tous",
    "apple", "samsung", "sony", "huawei", "xiaomi", "lenovo", "midea", "haier",
    "hisense", "tcl", "zte", "alibaba", "tencent", "byd", "sinopec", "cosco",
    "foxconn", "anker", "shein", "temu", "nike", "adidas", "decathlon", "bosch",
    "siemens", "philips", "nestle", "danone", "coca", "pepsi", "heineken",
    "toyota", "honda", "volkswagen", "tesla", "bmw", "mercedes", "renault",
)


def _safe(name: str) -> bool:
    lowered = unicodedata.normalize("NFKD", name.lower())
    return not any(bad in lowered for bad in _COMPANY_BLOCKLIST)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _pick_name(rng: random.Random, used: set[str], make) -> str:
    """Nombre aún no usado; si el espacio se agota, repite uno (un mismo
    proveedor puede emitir varias facturas y el bucle no debe colgarse)."""
    fallback = make()
    for _ in range(24):
        candidate = make()
        if not _safe(candidate):
            continue
        if candidate not in used:
            used.add(candidate)
            return candidate
        fallback = candidate
    return fallback


def make_buyer(rng: random.Random, used: set[str]) -> Party:
    sector, code, local = rng.choice(BUYER_SECTORS_ES)
    name = _pick_name(
        rng, used,
        lambda: f"{rng.choice(_ES_FIRST)} {rng.choice(SPANISH_CITY_SUFFIX)} {code} S.L.",
    )
    city, cp_prefix, _, _ = rng.choice(SPANISH_CITIES)
    street = rng.choice(SPANISH_STREETS)
    number = rng.randint(3, 180)
    postcode = f"{cp_prefix}{rng.randint(0, 99):02d}"
    nif = company_nif(rng)
    domain = f"{_slug(name)}.es"
    return Party(
        role="buyer", name=name, address=f"{street}, {number}", city=city,
        postcode=postcode, country="ES", country_name_es="España", country_name_en="Spain",
        tax_id=nif, tax_label="NIF", eori=eori("ES", nif), contact=f"{rng.choice(('Marta','Laura','Javier','Sergio','Elena','Pablo','Nuria','Carlos'))} {rng.choice(('Gil','Ferrer','Navarro','Romero','Serrano','Vidal','Campos','Roca'))}",
        phone=f"+34 {rng.randint(600, 699)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
        email=f"compras@{domain}",
    )


def make_supplier(rng: random.Random, country: str, used: set[str]) -> Party:
    if country == "ES":
        return make_es_supplier(rng, used)
    if country == "CN":
        return make_cn_supplier(rng, used)
    if country in _EU_SUPPLIERS:
        return make_eu_supplier(rng, country, used)
    return make_other_supplier(rng, country, used)


def _bank(rng: random.Random, country: str) -> tuple[str, str, str]:
    idx = rng.randrange(len(_BANK_NAMES))
    # Longitud total del IBAN (no del BBAN).
    lengths = {"ES": 24, "DE": 22, "FR": 27, "IT": 27, "PT": 25, "NL": 18, "PL": 28, "BE": 16,
               "GB": 22}
    number = iban(country, lengths, rng) if country in lengths else ""
    return _BANK_NAMES[idx], number, bic(rng, country)


def make_es_supplier(rng: random.Random, used: set[str]) -> Party:
    name = _pick_name(
        rng, used,
        lambda: f"{rng.choice(_ES_FIRST)} {rng.choice(('Suministros','Comercial','Manufacturas','Distribuciones','Talleres','Industrias'))} {rng.choice(('Levante','del Sur','Ibérica','Central','del Ebro','Mediterránea'))} S.L.",
    )
    city, cp_prefix, _, _ = rng.choice(SPANISH_CITIES)
    nif = company_nif(rng)
    bank_name, account, swift = _bank(rng, "ES")
    return Party(
        role="supplier", name=name, address=f"{rng.choice(SPANISH_STREETS)}, {rng.randint(3, 180)}",
        city=city, postcode=f"{cp_prefix}{rng.randint(0, 99):02d}", country="ES",
        country_name_es="España", country_name_en="Spain", tax_id=nif, tax_label="NIF",
        eori=eori("ES", nif),
        contact=f"{rng.choice(('Ana','Raúl','Luis','Silvia','Iván','Teresa'))} {rng.choice(('Molina','Ortega','Pascual','Herrero','Lozano','Cano'))}",
        phone=f"+34 {rng.randint(900, 999)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
        email=f"facturacion@{_slug(name)}.es", bank_name=bank_name, iban=account, bic=swift,
    )


def make_cn_supplier(rng: random.Random, used: set[str]) -> Party:
    city = rng.choice(_SUPPLIER_FIRST_CN)
    name = _pick_name(
        rng, used,
        lambda: f"{city} {rng.choice(_SUPPLIER_SECOND_CN)} {rng.choice(_SUPPLIER_KIND_CN)}",
    )
    code = usci(rng, region=rng.choice(("3302", "4403", "3205", "3702", "3502", "3101")))
    return Party(
        role="supplier", name=name, address=f"{rng.randint(10, 999)} {rng.choice(('Jiangnan','Binjiang','Haishu','Yinzhou','Xingang','Huangguan'))} Road, {rng.choice(('Ningbo','Shenzhen','Guangzhou','Qingdao','Xiamen','Suzhou'))}",
        city=city, postcode=f"{rng.randint(200000, 518000)}", country="CN",
        country_name_es="China", country_name_en="China",
        tax_id=code, tax_label="USCI (统一社会信用代码)",
        eori=None,
        contact=f"{rng.choice(('Chen','Li','Wang','Zhang','Liu','Huang'))} {rng.choice(('Wei','Jing','Ming','Hao','Yan','Lei'))}",
        phone=supplier_phone(rng, "CN"),
        email=f"sales@{_slug(city + rng.choice(_SUPPLIER_SECOND_CN))}.com",
        bank_name=rng.choice(("Ningbo Commercial Bank", "Pearl River Bank",
                              "East Asia Trade Bank", "China Meridian Bank",
                              "Harbour Savings Bank")),
        iban=None, bic=None,
    )


def make_eu_supplier(rng: random.Random, country: str, used: set[str]) -> Party:
    name = _pick_name(
        rng, used,
        lambda: f"{rng.choice(_EU_SUPPLIERS[country])} {rng.choice(('Handels GmbH','S.A.S.','S.r.l.','Lda.','B.V.','Sp. z o.o.','NV'))}",
    )
    city, cp_prefix, _ = rng.choice(_EU_CITIES[country])
    tax = {"DE": de_vat, "FR": fr_vat, "IT": it_vat, "PT": pt_vat, "NL": nl_vat,
           "PL": pl_vat, "BE": be_vat}[country](rng)
    bank_name, account, swift = _bank(rng, country)
    es_name, en_name = _COUNTRY_NAMES[country]
    return Party(
        role="supplier", name=name, address=f"{rng.choice(('Hafenstrasse','Rue du Port','Via del Porto','Rua do Comércio','Havenweg','ul. Portowa','Quai du Commerce'))} {rng.randint(2, 120)}",
        city=city, postcode=f"{cp_prefix}{rng.randint(0, 999):03d}" if len(cp_prefix) == 2 else f"{cp_prefix}{rng.randint(0, 99):02d}",
        country=country, country_name_es=es_name, country_name_en=en_name,
        tax_id=tax, tax_label="VAT", eori=eori(country, tax[2:]),
        contact=contact(rng, country),
        phone=supplier_phone(rng, country),
        email=f"orders@{_slug(name)}.{country.lower()}", bank_name=bank_name, iban=account, bic=swift,
    )


def make_other_supplier(rng: random.Random, country: str, used: set[str]) -> Party:
    city, cp_prefix, _ = rng.choice(_EXTRA_EU_CITIES[country])
    stems = {"US": ("Trading Inc.", "Industries LLC", "Supply Co."),
             "IN": ("Exports Pvt. Ltd.", "Trading Pvt. Ltd.", "Industries Ltd."),
             "TR": ("Dis Ticaret Ltd. Sti.", "Sanayi A.S.", "Ihracat Ltd."),
             "GB": ("Trading Ltd.", "Industries Ltd.", "Supplies Ltd."),
             "VN": ("Trading JSC", "Import Export JSC", "Production Co., Ltd."),
             "BR": ("Comércio Ltda.", "Indústria S.A.", "Importadora Ltda."),
             "MA": ("SARL", "S.A.R.L. Export", "Industrie SARL"),
             "TW": ("Trading Co., Ltd.", "Enterprise Co., Ltd.", "Industrial Corp."),
             "KR": ("Co., Ltd.", "Trading Co., Ltd.", "Industrial Co., Ltd."),
             "JP": ("Co., Ltd.", "Trading Co., Ltd.", "Corporation"),
             "PK": ("Trading Co.", "Exports (Pvt.) Ltd.", "Industries Ltd."),
             "BD": ("Trading Ltd.", "Exporters Ltd.", "Garments Ltd."),
             "TH": ("Co., Ltd.", "Trading Co., Ltd.", "Industries Co., Ltd."),
             "MX": ("Comercializadora S.A. de C.V.", "Importadora S.A. de C.V.", "Industrias S.A."),
             "ID": ("PT", "Trading Co.", "Industri PT")}
    name = _pick_name(
        rng, used,
        lambda: f"{city.split(',')[0].split()[0]} {rng.choice(('Meridian','Harbour','Summit','Crescent','Atlas','Pacific','Golden','Silver'))} {rng.choice(stems[country])}",
    )
    tax = {
        "US": ("", "Federal Tax ID"),
        "IN": (gstin(rng), "GSTIN"),
        "TR": (f"{rng.randint(1000000000, 9999999999)}", "VKN"),
        "GB": (gb_vat(rng), "VAT"),
        "VN": (f"{rng.randint(1000000000, 9999999999)}", "Tax code"),
        "BR": (cnpj(rng), "CNPJ"),
        "MA": (f"{rng.randint(100000000000000, 999999999999999)}", "ICE"),
        "TW": (f"{rng.randint(10000000, 99999999)}", "Tax ID"),
        "KR": (f"{rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10000, 99999)}", "Business No."),
        "JP": (f"{rng.randint(1000000000000, 9999999999999)}", "Corporate No."),
        "PK": (f"{rng.randint(1000000, 9999999)}-{rng.randint(1, 9)}", "NTN"),
        "BD": (f"{rng.randint(100000000, 999999999)}", "BIN"),
        "TH": (f"{rng.randint(1000000000000, 9999999999999)}", "Tax ID"),
        "MX": (f"RFC {''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(4))}{rng.randint(100000, 999999)}{''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ0123456789') for _ in range(3))}", "RFC"),
        "ID": (f"{rng.randint(10, 99)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}.{rng.randint(1, 9)}-{rng.randint(100, 999)}.{rng.randint(100, 999)}", "NPWP"),
    }[country]
    es_name, en_name = _COUNTRY_NAMES[country]
    return Party(
        role="supplier", name=name,
        address=f"{rng.randint(10, 999)} {rng.choice(('Harbour','Industrial','Commerce','Market','Riverside','North'))} {rng.choice(('Road','Street','Avenue','Park'))}",
        city=city, postcode=str(cp_prefix), country=country,
        country_name_es=es_name, country_name_en=en_name,
        tax_id=tax[0], tax_label=tax[1], eori=None,
        contact=contact(rng, country),
        phone=supplier_phone(rng, country),
        email=f"export@{_slug(name)[:18]}.com",
        bank_name=f"{rng.choice(('First','Union','Pacific','Atlas','Harbour'))} Bank",
        iban=None, bic=bic(rng, country),
    )


# Rutas comerciales verosímiles: (puerto origen, puerto destino, tránsito)
SEA_ROUTES = {
    "CN": [("Ningbo", "Valencia", 30), ("Shanghai", "Barcelona", 32), ("Shenzhen", "Valencia", 29),
           ("Qingdao", "Algeciras", 34), ("Xiamen", "Valencia", 31)],
    "IN": [("Nhava Sheva", "Valencia", 24), ("Chennai", "Barcelona", 26)],
    "TR": [("Istanbul", "Valencia", 7), ("Izmir", "Barcelona", 8)],
    "VN": [("Hai Phong", "Valencia", 33), ("Cat Lai", "Barcelona", 34)],
    "BR": [("Santos", "Valencia", 18), ("Santos", "Algeciras", 17)],
    "MA": [("Casablanca", "Algeciras", 2), ("Tanger Med", "Valencia", 2)],
    "TW": [("Kaohsiung", "Barcelona", 33)],
    "KR": [("Busan", "Valencia", 34)],
    "JP": [("Yokohama", "Barcelona", 36)],
    "PK": [("Karachi", "Valencia", 26)],
    "BD": [("Chittagong", "Valencia", 30)],
    "TH": [("Laem Chabang", "Barcelona", 32)],
    "MX": [("Manzanillo", "Valencia", 24)],
    "ID": [("Tanjung Priok", "Barcelona", 30)],
    "US": [("New York", "Valencia", 15), ("Savannah", "Valencia", 16)],
    "GB": [("Felixstowe", "Bilbao", 3)],
    "IT": [("Genova", "Valencia", 3), ("Livorno", "Barcelona", 4)],
    "FR": [("Le Havre", "Bilbao", 4), ("Marseille", "Valencia", 3)],
    "PT": [("Leixões", "Vigo", 2), ("Lisboa", "Valencia", 4)],
    "DE": [("Hamburg", "Bilbao", 6)],
    "NL": [("Rotterdam", "Bilbao", 6)],
    "PL": [("Gdansk", "Bilbao", 9)],
    "BE": [("Antwerpen", "Bilbao", 5)],
}

EU_AIRPORTS = {
    "DE": ("FRA", "MUC", "DUS"), "FR": ("CDG", "LYS", "MRS"), "IT": ("MXP", "FCO", "VCE"),
    "PT": ("LIS", "OPO"), "NL": ("AMS",), "PL": ("WAW", "GDN"), "BE": ("BRU",),
}
EXTRA_AIRPORTS = {
    "CN": ("PVG", "SZX", "CAN", "HGH"), "US": ("JFK", "LAX", "ORD"), "IN": ("DEL", "BOM", "MAA"),
    "TR": ("IST", "ADB"), "GB": ("LHR", "MAN"), "VN": ("SGN", "HAN"), "BD": ("DAC",),
    "PK": ("KHI", "LHE"), "MA": ("CMN",), "TW": ("TPE", "KHH"), "KR": ("ICN", "PUS"),
    "JP": ("NRT", "KIX"), "TH": ("BKK",), "MX": ("MEX",), "ID": ("CGK",),
}
SPANISH_AIRPORTS = ("MAD", "BCN", "VLC")

VESSELS = [
    ("Aurora Meridian", "642W"), ("Blue Cordillera", "118E"), ("Costa Levante", "307N"),
    ("Nordic Serenity", "551S"), ("Pacific Haven", "744W"), ("Atlantic Drift", "226E"),
    ("Meridian Star", "819N"), ("Albatros Bay", "433S"),
]
SHIP_LINES = ["Meridian Line", "BlueCrest Shipping", "Nordhav Shipping", "Transoceanic Carriers"]

CUSTOMS_OFFICES = {
    "Valencia": "ES002001", "Barcelona": "ES002003", "Madrid": "ES002007",
    "Algeciras": "ES002101", "Bilbao": "ES002201", "Sevilla": "ES002301",
    "Zaragoza": "ES002401", "Alicante": "ES002501", "Vigo": "ES002601",
    "Las Palmas": "ES003501", "Murcia": "ES002701", "Gijón": "ES002801",
}

_PHONE_PREFIX = {
    "ES": 34, "DE": 49, "FR": 33, "IT": 39, "PT": 351, "NL": 31, "PL": 48, "BE": 32,
    "CN": 86, "US": 1, "IN": 91, "TR": 90, "GB": 44, "VN": 84, "BR": 55, "MA": 212,
    "TW": 886, "KR": 82, "JP": 81, "PK": 92, "BD": 880, "TH": 66, "MX": 52, "ID": 62,
}


_CONTACTS = {
    "ES": [("Marta", "Gil"), ("Javier", "Roca"), ("Elena", "Campos")],
    "DE": [("Klaus", "Bauer"), ("Anna", "Schulz"), ("Jan", "Wagner"), ("Petra", "Hoffmann")],
    "FR": [("Marie", "Dubois"), ("Julien", "Moreau"), ("Camille", "Lefevre")],
    "IT": [("Luca", "Rossi"), ("Giulia", "Bianchi"), ("Marco", "Ferrari")],
    "PT": [("João", "Silva"), ("Sofia", "Costa"), ("Miguel", "Pereira")],
    "NL": [("Jan", "de Vries"), ("Sanne", "Bakker"), ("Rik", "Jansen")],
    "PL": [("Ewa", "Nowak"), ("Piotr", "Kowalski"), ("Anna", "Wisniewska")],
    "BE": [("Luc", "Peeters"), ("Els", "Janssens")],
    "CN": [("Chen", "Wei"), ("Li", "Jing"), ("Wang", "Ming"), ("Zhang", "Hao")],
    "US": [("David", "Smith"), ("Emily", "Johnson"), ("Michael", "Brown")],
    "IN": [("Priya", "Patel"), ("Arjun", "Sharma"), ("Neha", "Iyer")],
    "TR": [("Ahmet", "Yilmaz"), ("Elif", "Demir"), ("Mehmet", "Kaya")],
    "GB": [("James", "Brown"), ("Sarah", "Wilson"), ("Tom", "Evans")],
    "VN": [("Minh", "Nguyen"), ("Linh", "Tran"), ("Huy", "Pham")],
    "BR": [("Carlos", "Silva"), ("Ana", "Souza"), ("Rafael", "Lima")],
    "MA": [("Youssef", "Benali"), ("Salma", "El Amrani"), ("Omar", "Tazi")],
    "TW": [("Wei", "Lin"), ("Mei", "Chen"), ("Chih", "Huang")],
    "KR": [("Jin", "Kim"), ("Min", "Park"), ("Seo", "Lee")],
    "JP": [("Hiro", "Tanaka"), ("Yuki", "Sato"), ("Ken", "Suzuki")],
    "PK": [("Ali", "Khan"), ("Sana", "Malik"), ("Imran", "Butt")],
    "BD": [("Rahim", "Ahmed"), ("Nusrat", "Islam"), ("Kamal", "Hossain")],
    "TH": [("Somchai", "Prasert"), ("Nok", "Suwan"), ("Anan", "Chai")],
    "MX": [("Carlos", "Hernández"), ("María", "López"), ("Jorge", "Ramírez")],
    "ID": [("Budi", "Santoso"), ("Sari", "Wijaya"), ("Agus", "Pratama")],
}


def contact(rng: random.Random, country: str) -> str:
    first, last = rng.choice(_CONTACTS.get(country, _CONTACTS["ES"]))
    return f"{first} {last}"


def supplier_phone(rng: random.Random, country: str) -> str:
    prefix = _PHONE_PREFIX.get(country, 34)
    if prefix in (1, 34, 39, 44, 49, 52, 55, 62, 66, 81, 82, 84, 86, 90, 91, 92, 351, 880, 886, 212):
        return f"+{prefix} {rng.randint(100, 999)} {rng.randint(100, 999)} {rng.randint(100, 999)}"
    return f"+{prefix} {rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


PAYMENT_TERMS_ES = [
    ("Transferencia bancaria a 30 días fecha factura", 30),
    ("Transferencia SEPA a 60 días", 60),
    ("50 % anticipo y 50 % contra documentos", 30),
    ("Pago a 90 días mediante confirming", 90),
    ("Transferencia a 15 días", 15),
    ("Pago a 30 días mediante pagaré", 30),
]
PAYMENT_TERMS_EN = [
    ("T/T 30 days from invoice date", 30),
    ("Net 60 days by bank transfer", 60),
    ("30% advance payment, balance against documents", 30),
    ("Irrevocable L/C at sight", 15),
    ("Net 90 days", 90),
    ("T/T in advance", 7),
    ("Net 45 days", 45),
]

PACKAGING = ["cartons", "pallets", "crates", "bags", "drums", "bales", "boxes"]
