"""Render a representative Resume Studio fixture for local visual QA."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from resume_studio import ResumeStudio, export_bundle  # noqa: E402
import fitz  # noqa: E402


def main() -> int:
    output = ROOT / "tmp" / "pdfs"
    output.mkdir(parents=True, exist_ok=True)
    studio = ResumeStudio(ROOT / "data", ROOT / "resume_templates")
    template = next(row for row in studio.list_templates() if row["id"] == "modern_professional")
    draft = {
        "contact": {
            "name": "Jordan Rivera",
            "email": "jordan.rivera@example.com",
            "phone": "(206) 555-0199",
            "location": "Seattle, Washington",
            "links": ["linkedin.com/in/jordanrivera"],
        },
        "target_title": "Senior Operations Manager",
        "summary": "Operations leader with 10 years of verified experience building reliable service teams, improving cross-functional workflows, and turning customer data into measurable execution priorities.",
        "skills": ["Operations Strategy", "Team Leadership", "Process Improvement", "Service Delivery", "Salesforce", "KPI Reporting", "Vendor Management"],
        "experience": [
            {
                "title": "Operations Lead",
                "employer": "Northwind Services",
                "location": "Seattle, Washington",
                "start_date": "January 2021",
                "end_date": "Present",
                "bullets": [
                    "Lead a 12-person service team across three operating regions while maintaining a verified 96 percent on-time response rate.",
                    "Redesigned the intake and escalation workflow, reducing average response time by 18 percent over two quarters.",
                    "Built weekly Salesforce reporting used by sales, finance, and service leaders to prioritize staffing and customer-risk decisions.",
                ],
            },
            {
                "title": "Program Coordinator",
                "employer": "Contoso Group",
                "location": "Tacoma, Washington",
                "start_date": "June 2016",
                "end_date": "December 2020",
                "bullets": [
                    "Coordinated vendor schedules, customer communications, and project documentation for a portfolio of regional service programs.",
                    "Introduced a shared quality checklist that reduced incomplete handoffs and improved audit readiness.",
                ],
            },
        ],
        "education": [{"credential": "Bachelor of Science in Business Administration", "school": "Washington State University", "location": "Pullman, Washington", "date": "2016"}],
        "certifications": ["Project Management Professional (PMP), 2023"],
        "projects": ["Service Capacity Model - combined demand, staffing, and response data to support quarterly workforce planning."],
        "awards": [],
        "federal_details": [],
        "cover_letter": "Dear Hiring Manager,\n\nI am excited to apply for the Senior Operations Manager role. My background combines hands-on service leadership with disciplined process improvement and cross-functional reporting.\n\nAt Northwind Services, I lead a 12-person team across three regions and redesigned the intake workflow to reduce response time by 18 percent. I would welcome the opportunity to bring that same practical, data-informed leadership to your organization.\n\nSincerely,\nJordan Rivera",
        "linkedin_headline": "Senior Operations Leader | Service Delivery | Process Improvement",
        "linkedin_about": "I build reliable operating systems and capable teams. My work connects service delivery, customer data, and practical process improvement.",
        "recruiter_email_subject": "Senior Operations Manager application - Jordan Rivera",
        "recruiter_email": "Hello, I am reaching out regarding the Senior Operations Manager position. My background includes leading multi-region service operations and delivering verified workflow improvements. I would welcome a conversation.",
        "interview_talking_points": ["How the intake redesign reduced response time by 18 percent.", "How Salesforce reporting aligned sales, finance, and service leaders."],
        "unconfirmed_claims": [],
    }
    bundle = export_bundle(draft, resume_type="private", template=template)
    for name, content in bundle.items():
        (output / name).write_bytes(content)
    for pdf_path in output.glob("*.pdf"):
        pdf = fitz.open(pdf_path)
        for index, page in enumerate(pdf, start=1):
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(output / f"{pdf_path.stem}-page-{index}.png")
        pdf.close()
    print(output / "resume.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
