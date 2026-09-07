from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.services.compliance_service import check_compliance
from backend.services.extraction_service import extract_declarations, get_ocr_result
from backend.services.inspection_service import UPLOAD_DIR, get_inspection_context


REPORT_TITLE = "Legal Metrology Compliance Inspection Report"
DISCLAIMER = "This report is an AI-assisted inspection aid. Final legal determination remains subject to verification by the authorized Legal Metrology authority."
DECLARATION_FIELDS = (
    "product_name", "manufacturer", "packer", "importer", "country_of_origin",
    "net_quantity", "mrp", "month_year_of_manufacture_or_packing",
    "best_before_or_use_by", "consumer_care", "unit_sale_price", "batch_or_lot_number",
)
SOURCE_TEXT_LABEL = "Source text"


def _text(value: Any, missing: str = "Not detected") -> str:
    if value in (None, ""):
        return missing
    return str(value)


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _status_value(declaration: dict[str, Any]) -> str:
    if declaration.get("status") == "needs_review":
        return "Manual review required"
    return _text(declaration.get("value"))


def _confidence(value: Any) -> str:
    if value is None:
        return "Unavailable"
    return f"{float(value) * 100:.1f}%"


def _bbox(value: Any) -> str:
    return _text(value, "Evidence region unavailable — manual verification required.")


def _table(data: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d7e2")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b365d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])
    table.setStyle(TableStyle(style))
    return table


def _footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#c9d7e2"))
    canvas.line(15 * mm, 13 * mm, 195 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#607286"))
    canvas.drawString(15 * mm, 8 * mm, DISCLAIMER)
    canvas.drawRightString(195 * mm, 8 * mm, f"Page {document.page}")
    canvas.restoreState()


def generate_report(inspection_id: str) -> BytesIO:
    context = get_inspection_context(inspection_id)
    if not context:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection data not found")
    try:
        ocr_result = get_ocr_result(inspection_id)
    except HTTPException as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OCR data not found for this inspection") from error

    extracted = extract_declarations(ocr_result)
    compliance = check_compliance(
        extracted["declarations"],
        str(context.get("product_category", "")),
        context,
        ocr_result.get("detections", []),
    )
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#0b365d"), spaceAfter=5))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#0b365d"), spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=7.5, leading=9))
    styles.add(ParagraphStyle(name="Tiny", parent=styles["BodyText"], fontSize=6.5, leading=8))
    styles.add(ParagraphStyle(name="Status", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8))

    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm, title=REPORT_TITLE, author="Legal Metrology Compliance Inspection System")
    story: list[Any] = [
        Paragraph("Legal Metrology Compliance Inspection System", styles["ReportTitle"]),
        Paragraph(REPORT_TITLE, styles["Heading1"]),
        Spacer(1, 4 * mm),
    ]
    metadata = [
        [Paragraph("Inspection ID", styles["Small"]), _paragraph(inspection_id, styles["Small"]), Paragraph("Inspection date", styles["Small"]), _paragraph(context.get("inspection_date"), styles["Small"])],
        [Paragraph("Place of inspection", styles["Small"]), _paragraph(context.get("inspection_place"), styles["Small"]), Paragraph("Generated", styles["Small"]), _paragraph(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), styles["Small"])],
    ]
    story.append(_table(metadata, [30 * mm, 62 * mm, 30 * mm, 58 * mm], header=False))

    story.append(Paragraph("Product Details", styles["Section"]))
    product = extracted["declarations"]
    product_rows = [
        [Paragraph("Product category", styles["Small"]), _paragraph(context.get("product_category"), styles["Small"])],
        [Paragraph("Product name", styles["Small"]), _paragraph(product.get("product_name", {}).get("value") or context.get("product_name"), styles["Small"])],
        [Paragraph("Manufacturer / packer / importer", styles["Small"]), _paragraph(product.get("manufacturer", {}).get("value") or product.get("packer", {}).get("value") or product.get("importer", {}).get("value") or context.get("manufacturer"), styles["Small"])],
        [Paragraph("Country of origin", styles["Small"]), _paragraph(product.get("country_of_origin", {}).get("value"), styles["Small"])],
        [Paragraph("Net quantity", styles["Small"]), _paragraph(product.get("net_quantity", {}).get("value"), styles["Small"])],
        [Paragraph("MRP", styles["Small"]), _paragraph(product.get("mrp", {}).get("value"), styles["Small"])],
        [Paragraph("Batch / lot", styles["Small"]), _paragraph(product.get("batch_or_lot_number", {}).get("value"), styles["Small"])],
    ]
    story.append(_table(product_rows, [58 * mm, 122 * mm], header=False))

    story.append(Paragraph("Extracted Declarations", styles["Section"]))
    declaration_rows = [[Paragraph(value, styles["Tiny"]) for value in ("Field", "Extracted value", "Status", "Confidence", SOURCE_TEXT_LABEL)]]
    for field in DECLARATION_FIELDS:
        declaration = product.get(field, {})
        declaration_rows.append([
            _paragraph(field, styles["Tiny"]),
            _paragraph(_status_value(declaration), styles["Tiny"]),
            _paragraph(declaration.get("status", "not_detected"), styles["Tiny"]),
            _paragraph(_confidence(declaration.get("confidence")), styles["Tiny"]),
            _paragraph(declaration.get("source_text"), styles["Tiny"]),
        ])
    story.append(_table(declaration_rows, [34 * mm, 34 * mm, 27 * mm, 22 * mm, 63 * mm]))

    checks = compliance["checks"]
    violations = [check for check in checks if check["status"] == "VIOLATION"]
    reviews = [check for check in checks if check["status"] == "REVIEW_REQUIRED"]
    compliant = [check for check in checks if check["status"] == "COMPLIANT"]
    story.append(Paragraph("Compliance Summary", styles["Section"]))
    summary = [
        [Paragraph("Overall status", styles["Small"]), _paragraph(compliance["overall_status"], styles["Small"])],
        [Paragraph("Compliance score", styles["Small"]), _paragraph(f"{compliance['compliance_score']}%", styles["Small"])],
        [Paragraph("Total checks", styles["Small"]), _paragraph(len(checks), styles["Small"])],
        [Paragraph("Compliant checks", styles["Small"]), _paragraph(len(compliant), styles["Small"])],
        [Paragraph("Confirmed violations", styles["Small"]), _paragraph(len(violations), styles["Small"])],
        [Paragraph("Manual-review checks", styles["Small"]), _paragraph(len(reviews), styles["Small"])],
    ]
    story.append(_table(summary, [58 * mm, 122 * mm], header=False))

    story.append(Paragraph("Compliance Checks", styles["Section"]))
    check_rows = [[Paragraph(value, styles["Tiny"]) for value in ("Field", "Rule ID", "Rule version", "Status", "Reason", SOURCE_TEXT_LABEL, "Confidence")]]
    for check in checks:
        check_rows.append([
            _paragraph(check.get("field_name", check.get("field")), styles["Tiny"]),
            _paragraph(check.get("rule_id"), styles["Tiny"]),
            _paragraph(check.get("rule_version"), styles["Tiny"]),
            _paragraph(check.get("status"), styles["Tiny"]),
            _paragraph(check.get("reason"), styles["Tiny"]),
            _paragraph(check.get("source_text"), styles["Tiny"]),
            _paragraph(_confidence(check.get("confidence")), styles["Tiny"]),
        ])
    story.append(_table(check_rows, [29 * mm, 23 * mm, 28 * mm, 23 * mm, 42 * mm, 35 * mm, 20 * mm]))

    story.append(Paragraph("Violations", styles["Section"]))
    if not violations:
        story.append(Paragraph("No confirmed violations for this inspection.", styles["BodyText"]))
    else:
        for check in violations:
            story.append(Paragraph(f"{_text(check.get('field_name'))} · {_text(check.get('rule_id'))}", styles["Heading3"]))
            story.append(Paragraph(_text(check.get("reason")), styles["BodyText"]))

    story.append(Paragraph("Manual Review", styles["Section"]))
    if not reviews:
        story.append(Paragraph("No manual review checks for this inspection.", styles["BodyText"]))
    else:
        story.append(Paragraph("Manual verification is required because the available image/OCR evidence is insufficient for a definitive compliance determination.", styles["BodyText"]))
        for check in reviews:
            story.append(Paragraph(f"{_text(check.get('field_name'))} · {_text(check.get('rule_id'))}: {_text(check.get('reason'))}", styles["Small"]))

    story.append(Paragraph("Evidence", styles["Section"]))
    image_name = context.get("uploaded_image")
    image_path = UPLOAD_DIR / image_name if isinstance(image_name, str) else None
    if image_path and image_path.is_file():
        image = Image(str(image_path), width=80 * mm, height=110 * mm, kind="proportional")
        story.append(image)
        story.append(Spacer(1, 3 * mm))
    evidence_checks = [check for check in checks if check.get("evidence_bbox") is not None or check.get("source_text")]
    if evidence_checks:
        evidence_rows = [[Paragraph(value, styles["Tiny"]) for value in ("Field", "Rule", SOURCE_TEXT_LABEL, "Confidence", "Evidence bbox")]]
        for check in evidence_checks:
            evidence_rows.append([
                _paragraph(check.get("field_name", check.get("field")), styles["Tiny"]),
                _paragraph(check.get("rule_id"), styles["Tiny"]),
                _paragraph(check.get("source_text"), styles["Tiny"]),
                _paragraph(_confidence(check.get("confidence")), styles["Tiny"]),
                _paragraph(_bbox(check.get("evidence_bbox")), styles["Tiny"]),
            ])
        story.append(_table(evidence_rows, [32 * mm, 25 * mm, 58 * mm, 22 * mm, 43 * mm]))
    else:
        story.append(Paragraph("Evidence region unavailable — manual verification required.", styles["BodyText"]))

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer
