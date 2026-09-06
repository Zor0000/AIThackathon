"""Generate text-based, fictional employment letters for the VeriSure demo."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_DIRECTORY = Path("output/pdf")

DOCUMENTS = (
    {
        "filename": "fictional-experience-letter-aarav-shah.pdf",
        "candidate": "Aarav Shah",
        "employer": "Northstar Labs",
        "title": "Senior Software Engineer",
        "employee_id": "NS-1042",
        "start_date": "January 2022",
        "end_date": "March 2024",
        "issue_date": "April 8, 2024",
        "employment_type": "Full-time, permanent",
        "department": "Product Engineering",
        "work_location": "Pune, Maharashtra, India",
        "separation_type": "Voluntary resignation",
        "exit_formalities": "Completed",
    },
    {
        "filename": "fictional-experience-letter-mira-kapoor.pdf",
        "candidate": "Mira Kapoor",
        "employer": "Blueharbor Systems",
        "title": "Quality Assurance Engineer",
        "employee_id": "BH-2087",
        "start_date": "June 2021",
        "end_date": "December 2023",
        "issue_date": "January 12, 2024",
        "employment_type": "Full-time, permanent",
        "department": "Quality Engineering",
        "work_location": "Bengaluru, Karnataka, India",
        "separation_type": "Voluntary resignation",
        "exit_formalities": "Completed",
    },
    {
        "filename": "fictional-experience-letter-dev-malhotra.pdf",
        "candidate": "Dev Malhotra",
        "employer": "Brightforge Solutions",
        "title": "Product Analyst",
        "employee_id": "BF-3156",
        "start_date": "September 2020",
        "end_date": "August 2022",
        "issue_date": "September 5, 2022",
        "employment_type": "Full-time, permanent",
        "department": "Product Operations",
        "work_location": "Mumbai, Maharashtra, India",
        "separation_type": "Voluntary resignation",
        "exit_formalities": "Completed",
    },
)


def build_pdf(document: dict[str, str]) -> None:
    output_path = OUTPUT_DIRECTORY / document["filename"]
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "LetterTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=25,
        textColor=HexColor("#102A43"),
        spaceAfter=3 * mm,
    )
    body = ParagraphStyle(
        "LetterBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=16,
        textColor=HexColor("#243B53"),
    )
    metadata = ParagraphStyle(
        "Metadata",
        parent=body,
        fontSize=8.5,
        leading=11,
        textColor=HexColor("#627D98"),
    )
    label = ParagraphStyle(
        "Label",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
    )
    value = ParagraphStyle(
        "Value",
        parent=body,
        fontSize=10,
        leading=14,
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=HexColor("#102A43"),
    )
    question = ParagraphStyle(
        "Question",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
    )
    answer = ParagraphStyle(
        "Answer",
        parent=body,
        fontSize=9,
        leading=12,
    )

    def header_footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFillColor(HexColor("#D64545"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(doc.leftMargin, A4[1] - 13 * mm, "FICTIONAL DEMO DOCUMENT - NOT VALID FOR EMPLOYMENT OR IDENTITY USE")
        canvas.setStrokeColor(HexColor("#D9E2EC"))
        canvas.line(doc.leftMargin, 16 * mm, A4[0] - doc.rightMargin, 16 * mm)
        canvas.setFillColor(HexColor("#627D98"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(doc.leftMargin, 10 * mm, "VeriSure synthetic test evidence")
        canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, "Page 1 of 1")
        canvas.restoreState()

    template = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=24 * mm,
        rightMargin=24 * mm,
        topMargin=28 * mm,
        bottomMargin=24 * mm,
        title="Fictional Experience Letter",
        author="VeriSure Demo",
        subject="Synthetic employment-verification test evidence",
    )
    facts = (
        ("Employer:", document["employer"]),
        ("Job Title:", document["title"]),
        ("Employee ID:", document["employee_id"]),
        ("Start Date:", document["start_date"]),
        ("End Date:", document["end_date"]),
    )
    fact_rows = [
        [Paragraph(key, label), Paragraph(value_text, value)]
        for key, value_text in facts
    ]
    facts_table = Table(fact_rows, colWidths=(42 * mm, 112 * mm), hAlign="LEFT")
    facts_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), HexColor("#F0F4F8")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, HexColor("#D9E2EC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    verification_questions = (
        (
            "1. Was the candidate employed by the organization during the period shown above?",
            "Yes",
        ),
        ("2. What was the candidate's employment type?", document["employment_type"]),
        ("3. Which department did the candidate work in?", document["department"]),
        ("4. What was the candidate's primary work location?", document["work_location"]),
        ("5. What was the recorded separation type?", document["separation_type"]),
        ("6. Were the candidate's exit formalities recorded as complete?", document["exit_formalities"]),
    )
    question_rows = [
        [Paragraph(prompt, question), Paragraph(response, answer)]
        for prompt, response in verification_questions
    ]
    question_table = Table(
        question_rows,
        colWidths=(108 * mm, 46 * mm),
        hAlign="LEFT",
        repeatRows=0,
    )
    question_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (1, 0), (1, -1), HexColor("#F7FAFC")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, HexColor("#D9E2EC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ]
        )
    )
    story = [
        Paragraph(document["employer"], title),
        Paragraph("SYNTHETIC EMPLOYMENT EXPERIENCE LETTER", metadata),
        Spacer(1, 8 * mm),
        Paragraph(f"Issue date: {document['issue_date']}", body),
        Spacer(1, 7 * mm),
        Paragraph("To whom it may concern,", body),
        Spacer(1, 4 * mm),
        Paragraph(
            f"This synthetic sample confirms the following historical employment record for <b>{document['candidate']}</b>. "
            "It is supplied solely as test evidence for the VeriSure product demonstration.",
            body,
        ),
        Spacer(1, 7 * mm),
        KeepTogether([facts_table]),
        Spacer(1, 6 * mm),
        Paragraph("Background Verification Questions", section_heading),
        Spacer(1, 2.5 * mm),
        KeepTogether([question_table]),
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=0.6, color=HexColor("#BCCCDC")),
        Spacer(1, 3.5 * mm),
        Paragraph(
            "Synthetic-record notice: Every organization, person, identifier, date, and employment detail in this document is fictional. "
            "This document is not issued by an employer, cannot verify employment, and must not be used for any real-world decision.",
            metadata,
        ),
    ]
    template.build(story, onFirstPage=header_footer)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for document in DOCUMENTS:
        build_pdf(document)


if __name__ == "__main__":
    main()
