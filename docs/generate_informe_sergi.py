#!/usr/bin/env python3
"""Generate the Sergi status report as a clean PDF with ReportLab."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).with_name("informe-sergi-2026-11-15.pdf")
NAVY = colors.HexColor("#0f172a")
TEAL = colors.HexColor("#0f766e")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#f8fafc")
LINE = colors.HexColor("#cbd5e1")
GREEN = colors.HexColor("#047857")
AMBER = colors.HexColor("#b45309")
RED = colors.HexColor("#b91c1c")

styles = getSampleStyleSheet()
body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.7, leading=14, textColor=colors.HexColor("#1f2937"), spaceAfter=3)
small = ParagraphStyle("small", parent=body, fontSize=8.2, leading=11.5, textColor=SLATE)
h1 = ParagraphStyle("h1", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=27, leading=32, textColor=NAVY, alignment=TA_LEFT, spaceAfter=4)
h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=10, spaceAfter=5)
h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=11.2, leading=14, textColor=TEAL, spaceBefore=7, spaceAfter=3)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=3, spaceAfter=2)
cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=10.8, spaceAfter=0)
cell_bold = ParagraphStyle("cell_bold", parent=cell, fontName="Helvetica-Bold")
header_cell = ParagraphStyle("header_cell", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
cover_meta = ParagraphStyle("cover_meta", parent=body, fontSize=9, leading=15, textColor=SLATE)
code = ParagraphStyle("code", parent=body, fontName="Courier", fontSize=7.4, leading=9.2, textColor=colors.HexColor("#0f172a"), leftIndent=0, rightIndent=0)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(16 * mm, 8 * mm, "Mytarik · TariffAI — documento interno")
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def table(rows, widths, header=True, font_size=8.5):
    data = []
    for r_index, row in enumerate(rows):
        data.append([
            Paragraph(str(value), header_cell if header and r_index == 0 else cell)
            for value in row
        ])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY if header else LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if header else NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]
    t.setStyle(TableStyle(style))
    return t


def p(text, style=body):
    return Paragraph(text, style)


def b(text):
    return Paragraph(text, bullet, bulletText="•")


def story():
    s = []
    s.append(Spacer(1, 30 * mm))
    s.append(Paragraph("MYTARIK · TARIFFAI", ParagraphStyle("k", parent=body, fontName="Helvetica-Bold", fontSize=9, textColor=TEAL, tracking=1.5)))
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("Informe de estado<br/>y puesta en marcha", h1))
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph("Clasificación arancelaria EU con IA local: CN8 / TARIC10", ParagraphStyle("sub", parent=body, fontSize=13, leading=18, textColor=SLATE)))
    s.append(Spacer(1, 7 * mm))
    s.append(table([
        ["Base técnica operativa", "Catálogo EU completo pendiente"],
    ], [55 * mm, 80 * mm], header=False, font_size=8.5))
    s.append(Spacer(1, 14 * mm))
    s.append(Paragraph("<b>Para:</b> Sergi<br/><b>Preparado por:</b> Seby<br/><b>Fecha:</b> 15 de noviembre de 2026<br/><b>Ámbito:</b> estado del proyecto, resultados verificados, riesgos y puesta en marcha<br/><b>Clasificación:</b> documento interno de trabajo — no asesoramiento jurídico", cover_meta))

    s.append(PageBreak())
    s.append(Paragraph("1. Resumen ejecutivo", h2))
    s.append(p("Mytarik ya no es un prototipo vacío. El proyecto tiene una base técnica funcional para clasificar mercancías con códigos <b>CN8/TARIC10</b>, una API y una interfaz web, una base vectorial, un clasificador EU separado del flujo HS6 y una batería de pruebas. También se ha validado el flujo con documentos sintéticos y se ha construido la infraestructura para ingerir decisiones EBTI."))
    s.append(p("La conclusión principal es clara:"))
    s.append(KeepTogether([
        p("<b>La arquitectura y el flujo EU funcionan; lo que falta es el dato operativo completo.</b>"),
        p("El catálogo TARIC completo ya está cargado: <b>25.878 códigos</b>. Ahora el reto es la precisión del clasificador con el catálogo real, no la falta de datos."),
    ]))

    s.append(Paragraph("2. Estado por bloques", h2))
    s.append(table([
        ["Bloque", "Estado", "Qué hay"],
        ["T1 — Parser TARIC", "<font color='#047857'><b>Terminado</b></font>", "Parser del fichero oficial de bienes, CN8/TARIC10, tests."],
        ["T2 — Ingesta EU", "<font color='#047857'><b>Terminado</b></font>", "25.878 códigos TARIC10 en Qdrant; 1.225.487 medidas indexadas."],
        ["T3 — Clasificador EU", "<font color='#047857'><b>Terminado</b></font>", "CN8/TARIC10, EU por defecto, legacy HS6 solo explícito, sin fallback."],
        ["T3.3 — Web/UI EU", "<font color='#047857'><b>Terminado</b></font>", "Tabla y detalle con CN8/TARIC10; legacy conservado."],
        ["T4 — Consulta HS6", "<font color='#047857'><b>Terminado</b></font>", "/hs6/lookup y /api/reference/hs6, separados del clasificador EU."],
        ["T5 — Documentos reales", "<font color='#b45309'><b>Regresión detectada</b></font>", "3 documentos reales, 10 líneas; CN8 3/10 y TARIC10 3/10."],
        ["Lote sintético híbrido", "<font color='#b45309'><b>Validado</b></font>", "100 facturas, 282 líneas; clasificación 8/10 en muestra."],
        ["EBTI", "<font color='#047857'><b>Completo</b></font>", "123.458 decisiones cargadas; colección green."],
        ["Catálogo TARIC completo", "<font color='#047857'><b>Cargado</b></font>", "2026/10 completo + medidas 2026/11."],
    ], [45 * mm, 35 * mm, 100 * mm]))
    s.append(p("Los tests EU/EBTI suman 43 pruebas y los tests T4 otras 7. El catálogo ya no es una muestra; la precisión real se mide en T5.", small))

    s.append(PageBreak())
    s.append(Paragraph("3. Qué funciona hoy", h2))
    s.append(Paragraph("Clasificación EU", h3))
    for item in [
        "El clasificador EU devuelve <b>CN8</b> y <b>TARIC10</b>; no devuelve HS6.",
        "<font name='Courier'>CLASSIFICATION_MODE=eu</font> es el modo por defecto.",
        "<font name='Courier'>legacy_hs6</font> solo se activa de forma explícita; no hay fallback automático.",
        "Las respuestas EU se serializan en la API web y se muestran en la UI.",
    ]:
        s.append(b(item))
    s.append(Paragraph("Consulta HS6 separada", h3))
    for item in [
        "<font name='Courier'>/hs6/lookup</font> usa el retriever HS6 y no llama al clasificador EU.",
        "La UI tiene una sección independiente con el aviso: <i>“Referencia internacional. No usar para la declaración aduanera UE.”</i>",
        "HS6 no contamina la tabla EU ni el payload del clasificador.",
    ]:
        s.append(b(item))
    s.append(Paragraph("Datos y evaluación", h3))
    for item in [
        "<font name='Courier'>hs_codes</font>: 5.613 códigos HS6 de referencia.",
        "<font name='Courier'>ebti_decisions</font>: 123.458 decisiones EBTI cargadas.",
        "Traducción local ES/EN con OPUS-MT + CTranslate2, sin Azure.",
        "Documentos reales: 3 documentos, 10 líneas, <b>3/10 CN8</b>.",
        "Lote sintético: 100 facturas, 282 líneas, clasificación <b>8/10</b> en muestra.",
        "Parser PDF corregido: la factura comercial pasó de 19 líneas extraídas a 4.",
    ]:
        s.append(b(item))

    s.append(Paragraph("4. Arquitectura actual", h2))
    s.append(Preformatted("""Navegador
   |
   v
webapp-frontend :3000
   |
   v
webapp-backend :8005  --->  TariffAI API :8004  --->  Qdrant :6333
                                  |
                                  v
                        Laguna S 2.1 Q4 :8084
                        (OpenAI-compatible, 64K)
                                  ^
                                  |
                        proxy Docker :8082""", style=ParagraphStyle("arch", parent=body, fontName="Courier", fontSize=8.2, leading=11, textColor=colors.HexColor("#0f172a"), backColor=LIGHT, borderPadding=6, leftIndent=0, rightIndent=0)))

    s.append(Paragraph("5. Decisiones de diseño", h2))
    for item in [
        "<b>EU-first:</b> la operativa diaria usa CN8/TARIC10. HS6 solo se consulta de forma explícita y separada.",
        "<b>Sin fallback silencioso:</b> si el modo EU falla, no se cae a HS6.",
        "<b>Sin Azure:</b> clasificación y traducción funcionan en local; no se necesitan credenciales de Azure.",
        "<b>EBTI no es TARIC:</b> las decisiones EBTI son jurisprudencia de apoyo, no el catálogo operativo.",
        "<b>Revisión humana:</b> la IA propone; el agente aduanero valida. No es asesoramiento jurídico.",
    ]:
        s.append(b(item))

    s.append(PageBreak())
    s.append(Paragraph("6. Resultados verificados", h2))
    s.append(table([
        ["Métrica", "Resultado"],
        ["Tests EU / EBTI", "<font color='#047857'><b>43 passed</b></font>"],
        ["Tests T4 HS6", "<font color='#047857'><b>7 passed</b></font>"],
        ["Build frontend", "<font color='#047857'><b>OK</b></font>"],
        ["Documentos sintéticos procesados", "3"],
        ["Líneas evaluadas", "10"],
        ["Aciertos CN8 (documentos reales)", "<font color='#b45309'><b>3 / 10</b></font>"],
        ["Facturas sintéticas generadas", "100"],
        ["Líneas sintéticas generadas", "282"],
        ["Parser: recuento de líneas", "<font color='#047857'><b>100 / 100</b></font>"],
        ["Parser: descripciones exactas", "<font color='#047857'><b>276 / 282 (97,9%)</b></font>"],
        ["Clasificación sintética CN8", "<font color='#b45309'><b>8 / 10</b></font>"],
        ["Error con confianza > 0,95", "<font color='#b91c1c'><b>1</b></font>"],
        ["Aciertos TARIC10 (catálogo real)", "<font color='#b45309'><b>3 / 10</b></font>"],
        ["Errores de integración", "<font color='#047857'><b>0</b></font>"],
    ], [105 * mm, 70 * mm]))
    s.append(p("El 10/10 anterior no era válido: se midió con solo 6 códigos de muestra. En documentos reales, con 25.878 códigos, el clasificador baja a 3/10. En el lote sintético híbrido sube a 8/10, pero comete un error con confianza 0,9776. Es un problema de precisión, ranking y calibración, no de catálogo.", small))

    s.append(Paragraph("7. Riesgos y limitaciones", h2))
    risks = [
        ("1. Precisión y calibración del clasificador — riesgo crítico.", "El catálogo ya está completo, pero T5 real baja a 3/10 y el lote sintético tiene un error con confianza 0,9776. Hay que añadir reranking, abstención y validación real antes de producción."),
        ("2. Medidas locales y CustomsPanel.", "Las 1.225.487 medidas están en SQLite, pero el panel aún no las consulta localmente; sigue usando el contrato TARIC remoto."),
        ("3. EBTI completo, pero falta explotación.", "Las 123.458 decisiones están cargadas. Falta usarlas como evidencia y mostrar su trazabilidad en la UI."),
        ("4. Agentes locales lentos.", "Hermes y OpenCode con Laguna funcionan, pero exploran y compactan demasiado. Laguna rinde ~13,8 tok/s (3 GPUs, 260 W). Son útiles para tareas pequeñas y revisión, no como ingenieros autónomos."),
        ("5. Sin commit y sin auditoría de producción.", "El trabajo está en el árbol local, sin commit. Faltan historial de aprobaciones, trazabilidad y aviso legal para cliente."),
    ]
    for title, text in risks:
        s.append(KeepTogether([p(f"<b>{title}</b>"), p(text)]))

    s.append(PageBreak())
    s.append(Paragraph("8. Lo que falta para ponerlo en marcha", h2))
    s.append(Paragraph("Bloque A — Datos EU (cargado)", h3))
    for item in [
        "Catálogo TARIC/CN completo descargado: 2026/10 + 2026/11.",
        "Ingerido: 25.878 códigos y 1.225.487 medidas.",
        "Programar la actualización diaria/semanal y versionar el catálogo. Pendiente.",
        "T5 real: 3/10 CN8. Lote sintético: 8/10. Pendiente reranking y calibración.",
        "Revisar 20 facturas sintéticas y validar contra TARIC antes de escalar.",
    ]:
        s.append(b(item))
    s.append(Paragraph("Bloque B — Medidas y aduana", h3))
    for item in [
        "Adaptar CustomsPanel a CN8/TARIC10.",
        "Añadir origen, régimen, antidumping, cuotas y códigos Y.",
        "Validar con un despacho aduanero real.",
    ]:
        s.append(b(item))
    s.append(Paragraph("Bloque C — Producto", h3))
    for item in [
        "Auditoría: quién aprobó cada código, cuándo y por qué.",
        "Informe exportable y aviso legal.",
        "Piloto con 50–100 facturas reales.",
    ]:
        s.append(b(item))

    s.append(Paragraph("Bloque D — Puesta en marcha técnica", h3))
    s.append(Preformatted("""cd /home/seby/mytarik

# 1. Servicios
docker compose up -d --build

# 2. Modelo local + proxy Docker
nohup /home/seby/llama.cpp/start-laguna.sh > /tmp/laguna-server.log 2>&1 &
nohup /home/seby/.local/bin/mytarik_llm_proxy.py > /tmp/mytarik-llm-proxy.log 2>&1 &

# 3. Comprobaciones
curl -s http://127.0.0.1:8084/v1/models
curl -s http://127.0.0.1:8005/api/health
curl -s http://127.0.0.1:8004/health

# 4. Tests
/home/seby/.venvs/mytarik-eu/bin/python -m pytest -q \\
  tariffai/tests/test_eu_classifier.py \\
  tariffai/tests/test_eu_retriever.py \\
  tariffai/tests/test_hs6_lookup.py

# 5. Evaluación sintética
/home/seby/.venvs/mytarik-eu/bin/python \\
  tariffai/scripts/eval_synthetic_documents.py --mode upload --include 01 --limit 1""", style=code))

    s.append(Paragraph("9. Decisión que necesitamos de Sergi", h2))
    s.append(table([
        ["Decisión", "Para qué"],
        ["Aprobar el plan de reranking y reglas de familia", "Subir la precisión real antes del piloto."],
        ["Definir el alcance del piloto", "50–100 facturas, un despacho, métricas de acierto y tiempo."],
        ["Confirmar el marco legal", "Aviso, responsabilidad, confidencialidad y revisión humana."],
        ["Validar el hardware/servicio", "Laguna y el stack local; o una alternativa cloud si se exige latencia."],
    ], [70 * mm, 105 * mm]))
    s.append(Spacer(1, 5 * mm))
    s.append(p("<b>Conclusión honesta:</b> Mytarik ya tiene el catálogo completo, EBTI completo y un generador sintético funcional. En documentos reales la precisión es 3/10; en el lote sintético es 8/10, con un error confiado. La diferencia entre “demo” y “producción” es reranking, calibración, medidas locales, auditoría y un piloto real."))
    s.append(Spacer(1, 3 * mm))
    s.append(p("Documento generado el 15/11/2026. Los códigos TARIC de los documentos sintéticos son ilustrativos; deben verificarse contra el TARIC oficial. Este informe no constituye asesoramiento jurídico ni una decisión vinculante.", small))
    return s


def main() -> None:
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title="Mytarik / TariffAI — Informe de estado",
        author="Seby",
        subject="Estado del proyecto y puesta en marcha",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
    doc.build(story())
    print(OUT)


if __name__ == "__main__":
    main()
