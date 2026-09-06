"""PDF report generation for completed employment-verification cases."""

from __future__ import annotations

from io import BytesIO
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .domain import ComparisonRow
from .storage import CaseRecord


def build_verification_report_pdf(
    *,
    case: CaseRecord,
    comparisons: Sequence[ComparisonRow],
    generated_at: str,
) -> bytes:
    """Build a compact, evidence-only report suitable for HR review."""

    stream = BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Employment Verification - {case.case_id}",
        author="VeriSure",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A"),
        alignment=TA_LEFT,
        spaceAfter=4 * mm,
    )
    heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=5 * mm,
        spaceAfter=2.5 * mm,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    cell = ParagraphStyle(
        "Cell",
        parent=body,
        fontSize=7.5,
        leading=9,
        wordWrap="CJK",
    )
    header_cell = ParagraphStyle(
        "HeaderCell",
        parent=cell,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    story = [
        Paragraph("Employment Verification Report", title),
        Paragraph(
            "Evidence summary for HR review. This report is not an automated hiring decision.",
            body,
        ),
        Spacer(1, 4 * mm),
    ]
    summary_data = [
        ["Case ID", _safe(case.case_id), "Generated", _safe(generated_at)],
        ["Employee", _safe(case.candidate_name), "Status", _safe(case.verification_status.value)],
        ["Document", _safe(case.document_name), "Fingerprint", _safe(case.document_sha256)],
    ]
    summary = Table(summary_data, colWidths=[24 * mm, 58 * mm, 25 * mm, 57 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E2E8F0")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E2E8F0")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([Paragraph("Case summary", heading), summary])

    story.append(Paragraph("Evidence comparison", heading))
    comparison_data = [
        [Paragraph(label, header_cell) for label in ("Field", "Employee PDF", "Former employer", "Analysis")]
    ]
    for row in comparisons:
        comparison_data.append(
            [
                Paragraph(_safe(row.field), cell),
                Paragraph(_safe(row.candidate_value), cell),
                Paragraph(_safe(row.employer_value), cell),
                Paragraph(_safe(row.result.value), cell),
            ]
        )
    comparison_table = Table(
        comparison_data,
        colWidths=[27 * mm, 48 * mm, 48 * mm, 35 * mm],
        repeatRows=1,
    )
    comparison_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(comparison_table)
    story.extend(
        [
            Paragraph("HR review note", heading),
            Paragraph(
                "Review any mismatches or unavailable evidence before recording a final HR conclusion.",
                body,
            ),
        ]
    )
    document.build(story)
    return stream.getvalue()


def _safe(value: object) -> str:
    text = str(value or "-")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
