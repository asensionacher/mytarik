import pytest

from app.invoice_parser import _is_product_line, parse_text


@pytest.mark.parametrize("description", [
    "jamón",
    "Jamón",
    "jamon",
    "chorizo",
    "desodorante",
    "Jamón cocido",
    "10 CAJAS DE JAMON",
    "100% COTTON",
    "FROMAGE BLANC",
])
def test_product_descriptions_are_kept(description):
    assert _is_product_line(description)


@pytest.mark.parametrize("line", [
    "",
    "---",
    "1/2",
    "page 2 of 3",
    "1.234,56 EUR",
    "12,00",
    "EUR",
    "N° FACTURA 123",
    "SUBTOTAL 1.234,56",
    "DESCRIPTION | QTY | PRICE",
    "IVA 21%",
    "2 kg",
    "IBAN ES91 2100 0418 4502 0005 1332",
    "INVOICE NO 42",
    "DATE 2024-01-15",
    "TOTAL 1.500,00",
    "BILL TO: Acme Corp",
    "PAYMENT TERMS: Net 30",
    "20 CTNS",
    "10 UDS",
    "IBAN: ES91",
    "Base imponible 1.234,56",
    "Forma de pago: transferencia",
    "Remitente: Juan Perez",
    "Port of loading: Shanghai",
])
def test_invoice_noise_is_dropped(line):
    assert not _is_product_line(line)


def test_short_descriptions_survive_text_parsing():
    parsed = parse_text("chorizo\njamón\ndesodorante".encode("utf-8"))
    assert parsed.descriptions == ["chorizo", "jamón", "desodorante"]


def test_noise_lines_are_not_descriptions():
    parsed = parse_text(
        "INVOICE 42\n1.234,56 EUR\njamón\n12,00".encode("utf-8"),
    )
    assert parsed.descriptions == ["jamón"]


def test_description_with_colon_is_kept():
    assert _is_product_line("Jamón: cocido")
    assert _is_product_line("Producto: jamón")
