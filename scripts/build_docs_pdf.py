#!/usr/bin/env python3
"""Build docs/technical/trading-portal-documentation.pdf from README.md (reportlab).

The PDF carries its provenance on page 1: generation time, the source
README's last-modified time, and the release tag it was built from, so a
reader can tell at a glance when it was made and what it describes.
"""
import datetime
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "README.md")
OUT = os.path.join(REPO, "docs", "technical", "trading-portal-documentation.pdf")
TAG = os.environ.get("PORTAL_DOC_TAG", "v1.1.0")

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                Paragraph, Spacer)

PAGE_W, PAGE_H = letter
MARGIN = 0.9 * inch

styles = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20,
                            leading=24, spaceAfter=4),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9,
                           leading=12, textColor="#555555", spaceAfter=2),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15,
                         leading=18, spaceBefore=14, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12,
                         leading=15, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                           leading=14, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", parent=None, fontName="Helvetica",
                             fontSize=10, leading=14, leftIndent=18,
                             firstLineIndent=0, bulletIndent=8, spaceAfter=3),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=9,
                           leading=12, leftIndent=12, spaceAfter=6,
                           backColor="#f4f4f4"),
}


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;"))


def inline(t):
    """Render `code` spans in monospace."""
    parts = re.split(r"(`[^`]+`)", t)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 2:
            out.append(f'<font name="Courier">{esc(p[1:-1])}</font>')
        else:
            out.append(esc(p))
    return "".join(out)


def md_to_flowables(text):
    flows = []
    para, in_code = [], False
    code_buf = []

    def flush_para():
        if para:
            flows.append(Paragraph(inline(" ".join(para)), styles["body"]))
            para.clear()

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                flows.append(Paragraph(esc("\n".join(code_buf)),
                                      styles["code"]))
                code_buf = []
            else:
                flush_para()
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(line.rstrip())
            continue
        if s.startswith("# "):
            flush_para()
            flows.append(Paragraph(esc(s[2:].strip()), styles["h1"]))
        elif s.startswith("## "):
            flush_para()
            flows.append(Paragraph(esc(s[3:].strip()), styles["h2"]))
        elif s.startswith("- "):
            flush_para()
            flows.append(Paragraph(inline(s[2:].strip()), styles["bullet"],
                                   bulletText="\u2022"))
        elif not s:
            flush_para()
        else:
            para.append(s)
    flush_para()
    return flows


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor("#888888")
    canvas.drawString(MARGIN, 0.55 * inch,
                      f"trading-portal docs \u00b7 generated {doc.gen_stamp} "
                      f"\u00b7 page {doc.page}")
    canvas.restoreState()


def main():
    md = open(SRC).read()
    src_mtime = datetime.datetime.fromtimestamp(
        os.path.getmtime(SRC)).strftime("%Y-%m-%d %H:%M")
    gen_stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    doc = BaseDocTemplate(OUT, pagesize=letter,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=0.9 * inch,
                          title="trading-portal README",
                          author="trading-portal docs builder")
    doc.gen_stamp = gen_stamp
    frame = Frame(MARGIN, 0.9 * inch, PAGE_W - 2 * MARGIN,
                  PAGE_H - MARGIN - 0.9 * inch)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame],
                                       onPage=footer)])

    story = [
        Paragraph("trading-portal", styles["title"]),
        Paragraph("Project documentation \u2014 generated from "
                  "<font name=\"Courier\">README.md</font>", styles["meta"]),
        Paragraph(f"Source last updated: {src_mtime} \u00b7 "
                  f"PDF generated: {gen_stamp} \u00b7 release: {TAG}",
                  styles["meta"]),
        Spacer(1, 10),
    ]
    story += md_to_flowables(md)
    doc.build(story)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
