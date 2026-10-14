"""
Step 4: Description (text + figures/tables) and topic of each requirement.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import pymupdf
from PIL import Image, ImageOps
from finder import Definition
from reader import Line, Page, PdfText

STATEMENT_END_RE = re.compile(r"^(Rationale|Guidance|Operational Rules|Engineering Rules)\b")
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s*([A-Za-z].*)$")
CAPTION_RE = re.compile(r"^(Figure|Table)\s+(\d+)\s*[:.\-–—]\s*(.*)$")
MARKER_RE = re.compile(r"^(?:[•▪◦●■–\-➢]|\(?[a-zA-Z]\)|\(?\d{1,2}[.)]|[ivx]{1,4}[.)])\s")
TOPIC_LEVEL = 2  # topics are "3.1"-style sections
INDENT = "    "
ZOOM = 2.0
INK = [0] * 13 + [255] * 243  # anything not almost white counts as ink when trimming

@dataclass
class Media:
    kind: str  # "Figure" or "Table"
    number: str  # empty for a table without caption
    title: str
    regions: list[tuple[int, float, float]]  # (page, top, bottom), several if split over pages

    @property
    def caption(self) -> str:
        return f"{self.kind} {self.number}: {self.title}" if self.number else "Table"

@dataclass
class Requirement:
    id: str
    topic: str
    description: str
    page: int
    media: list[Media] = field(default_factory=list[Media])
    definition: Definition | None = None
    traceability: str = ""

def body_font_size(doc: PdfText) -> float:
    return Counter(l.size for l in doc.lines).most_common(1)[0][0]

def is_heading(line: Line, body_size: float) -> bool:
    return (line.table is None and HEADING_RE.match(line.text) is not None
            and (line.bold or line.size >= body_size + 1.5))

@dataclass
class Heading:
    number: str
    title: str
    page: int
    top: float

def section_headings(doc: PdfText) -> list[Heading]:
    body = body_font_size(doc)
    out: list[Heading] = []
    for line in doc.lines:
        if is_heading(line, body):
            m = HEADING_RE.match(line.text)
            assert m
            number, text = m.group(1), m.group(2).strip()
            # take whichever title isn't in capitals: R2DATO's headings are in
            # small caps, X2R3's table of contents too
            candidates = [c for c in (text, doc.toc.get(number)) if c]
            readable = [c for c in candidates if not c.isupper()]
            out.append(Heading(number, (readable or candidates)[0].rstrip(" ."), line.page, line.top))
    return out

def _topic(headings: list[Heading], page: int, top: float) -> str:
    before = [h for h in headings if (h.page, h.top) < (page, top)]
    return next((h.title for h in reversed(before) if h.number.count(".") == TOPIC_LEVEL - 1), "")

def _statement(doc: PdfText, start: Line, stops: set[int], body_size: float) -> list[Line]:
    # from the ID line to Rationale/Guidance/..., the next requirement or the next heading
    lines = doc.lines
    i = next(k for k, l in enumerate(lines) if l is start)
    out: list[Line] = []
    for line in lines[i + 1:]:
        if id(line) in stops or is_heading(line, body_size):
            break
        if line.table is None and STATEMENT_END_RE.match(line.text):
            break
        out.append(line)
    return out

def _figure_regions(doc: PdfText, cap: Line, upper: float) -> list[tuple[int, float, float]]:
    # The figure is what sits between the last paragraph line and the caption.
    # Paragraph lines are wide; the short labels inside the figure are not.
    page = doc.page(cap.page)
    above = [l for l in page.lines if upper <= l.top and l.bottom < cap.top - 1]
    wide = 0.5 * (page.width - 140)
    paragraphs = [l for l in above if l.x1 - l.x0 > wide]
    for prev, line in zip(above, above[1:]):
        if prev in paragraphs and abs(line.x0 - prev.x0) < 5 and line.top - prev.bottom < 8:
            paragraphs.append(line)
    top = max([upper] + [l.bottom for l in paragraphs])
    return [(cap.page, top + 2, cap.bottom + 2)]

def _table_regions(doc: PdfText, cap: Line) -> list[tuple[int, float, float]]:
    p = doc.page(cap.page)
    above = [t.bbox for t in p.tables if t.bbox[3] <= cap.top + 2 and cap.top - t.bbox[3] < 40]
    below = [t.bbox for t in p.tables if t.bbox[1] >= cap.bottom - 2 and t.bbox[1] - cap.bottom < 40]
    if above:  # X2Rail puts the caption under the table
        box = max(above, key=lambda b: b[3])
        regions = [(p.number, box[1] - 2, cap.bottom + 2)]
        page = p
        while box[1] - page.body_top < 25 and page.number > 1:  # table started on the previous page
            page = doc.page(page.number - 1)
            prev = [t.bbox for t in page.tables if page.body_bottom - t.bbox[3] < 60]
            if not prev:
                break
            box = max(prev, key=lambda b: b[3])
            regions.insert(0, (page.number, box[1] - 2, box[3] + 2))
        return regions
    if below:  # R2DATO puts it above
        box = min(below, key=lambda b: b[1])
        regions = [(p.number, cap.top - 2, box[3] + 2)]
        page = p
        while page.number < len(doc.pages) and page.body_bottom - box[3] < 60:
            page = doc.page(page.number + 1)
            nxt = [t.bbox for t in page.tables if t.bbox[1] - page.body_top < 25]
            if not nxt:
                break
            box = min(nxt, key=lambda b: b[1])
            regions.append((page.number, box[1] - 2, box[3] + 2))
        return regions
    return [(p.number, max(p.body_top, cap.top - 220), cap.bottom + 2)]

def _media(doc: PdfText, start: Line, statement: list[Line]) -> tuple[list[Media], set[int]]:
    media: list[Media] = []
    covered: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for line in statement:
        m = CAPTION_RE.match(line.text)
        if not m or line.table is not None:
            continue
        kind, number, title = m.group(1), m.group(2), m.group(3).strip()
        if (kind, number) in seen:
            continue
        if not title and any((c := CAPTION_RE.match(l.text)) and c.group(1, 2) == (kind, number) and c.group(3)
                             for l in statement):
            continue  # a bare "Table 8:" label, the real caption comes later
        seen.add((kind, number))
        upper = start.bottom if line.page == start.page else doc.page(line.page).body_top
        regions = _figure_regions(doc, line, upper) if kind == "Figure" else _table_regions(doc, line)
        media.append(Media(kind, number, title, regions))

    # tables without a caption
    if statement:
        last = statement[-1]
        for page_no in range(start.page, last.page + 1):
            for t in doc.page(page_no).tables:
                pos = (page_no, t.bbox[1])
                if not (start.page, start.top) < pos <= (last.page, last.bottom):
                    continue
                if any(r[0] == page_no and r[1] - 6 <= t.bbox[1] <= r[2] + 6 for x in media for r in x.regions):
                    continue
                media.append(Media("Table", "", "", [(page_no, t.bbox[1] - 2, t.bbox[3] + 2)]))

    for line in statement:
        if line.table is not None or any(r[0] == line.page and r[1] - 1 <= line.top and line.bottom <= r[2] + 1
                                         for x in media for r in x.regions):
            covered.add(id(line))
    media.sort(key=lambda x: x.regions[0][:2])
    return media, covered

@dataclass
class _Entry:
    x0: float
    text: str
    item: bool

def format_lines(lines: list[Line]) -> str:
    # Same layout as the manual reference: wrapped lines joined, and each list
    # item or indented line on its own line, 4 spaces per level.
    entries: list[_Entry] = []
    prev: Line | None = None
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        item = MARKER_RE.match(text) is not None
        new = (prev is None or item or prev.text.rstrip().endswith(":")
               or (prev.page == line.page and line.top - prev.bottom > 8)
               or line.x0 < prev.x0 - 3
               or (line.x0 > prev.x0 + 3 and not (entries[-1].item and line.x0 - entries[-1].x0 <= 30)))
        if new:
            entries.append(_Entry(line.x0, text, item))
        else:
            entries[-1].text += " " + text
        prev = line
    if not entries:
        return ""
    base = min(e.x0 for e in entries)
    steps = sorted({round(e.x0) for e in entries if e.x0 > base + 3})
    clusters: list[int] = []
    for s in steps:
        if not clusters or s - clusters[-1] > 6:
            clusters.append(s)
    out: list[str] = []
    for e in entries:
        level = sum(1 for c in clusters if e.x0 >= c - 3)
        out.append(INDENT * level + re.sub(r"\s+", " ", e.text))
    return "\n".join(out)

def format_cell(cell: str) -> str:
    entries: list[str] = []
    for raw in cell.split("\n"):
        text = raw.strip()
        if not text:
            continue
        if not entries or MARKER_RE.match(text) or entries[-1].rstrip().endswith(":"):
            entries.append((INDENT if MARKER_RE.match(text) else "") + text)
        else:
            entries[-1] += " " + text
    return "\n".join(entries)

def _row_description(doc: PdfText, d: Definition) -> str:
    # a row cut by a page break goes on in the first table of the next page
    assert d.row is not None and d.table is not None and d.row_index is not None
    parts = d.row[1:]
    page: Page = doc.page(d.page)
    table, r = page.tables[d.table], d.row_index + 1
    while True:
        if r >= len(table.rows):
            if page.number >= len(doc.pages) or page.body_bottom - table.bbox[3] > 60:
                break
            page = doc.page(page.number + 1)
            if not page.tables or page.tables[0].bbox[1] - page.body_top > 25:
                break
            table, r = page.tables[0], 0
            continue
        cells = [(c or "").strip() for c in table.rows[r]]
        filled = [c for c in cells if c]
        if cells and cells[0]:
            break  # next requirement
        if filled and filled != ["Description"]:
            parts.extend(filled)
        r += 1
    return "\n".join(format_cell(p) for p in parts)

def describe(doc: PdfText, definitions: list[Definition]) -> list[Requirement]:
    headings = section_headings(doc)
    body_size = body_font_size(doc)
    stops = {id(d.line) for d in definitions}
    out: list[Requirement] = []
    for d in definitions:
        topic = _topic(headings, d.page, d.line.top)
        if d.row is not None:
            out.append(Requirement(d.id, topic, _row_description(doc, d), d.page, [], d))
            continue
        statement = _statement(doc, d.line, stops, body_size)
        media, covered = _media(doc, d.line, statement)
        text = format_lines([l for l in statement if id(l) not in covered and not CAPTION_RE.match(l.text)])
        out.append(Requirement(d.id, topic, text, d.page, media, d))
    return out

def render_media(pdf_path: Path, media: Media) -> bytes:
    parts: list[Image.Image] = []
    with pymupdf.open(pdf_path) as pdf:
        for page_no, top, bottom in media.regions:
            page = pdf[page_no - 1]
            clip = pymupdf.Rect(0, max(top, 0), page.rect.width, min(bottom, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=clip)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            box = ImageOps.invert(img).convert("L").point(INK).getbbox()
            if box:
                pad = int(4 * ZOOM)
                img = img.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                                min(box[2] + pad, img.width), min(box[3] + pad, img.height)))
            parts.append(img)
    out = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts)), "white")
    y = 0
    for p in parts:
        out.paste(p, (0, y))
        y += p.height
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()