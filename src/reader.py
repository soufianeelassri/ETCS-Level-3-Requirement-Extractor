"""
Step 2: Read a PDF into positioned lines and tables, without headers, footers or TOC.
"""

import logging
import re
from collections import Counter
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path
import pdfplumber

log = logging.getLogger(__name__)

LINE_TOLERANCE = 3  # pt
MARGIN_BAND = 0.15  # look for headers/footers in the top and bottom 15 % of the page
REPEAT_RATIO = 0.3  # ...and keep those found on at least 30 % of the pages
TOC_RE = re.compile(r"\.{4,}|(?:\. ){4,}")
TOC_ENTRY_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.+?)\s*(?:\.\s*){4,}\s*\d+\s*$")
TOC_START_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(\D.*)$")


@dataclass
class Line:
    page: int
    top: float
    bottom: float
    x0: float
    x1: float
    text: str
    size: float
    bold: bool
    table: int | None = None  # index of the table it sits in, if any


@dataclass
class Table:
    bbox: tuple[float, float, float, float]
    rows: list[list[str | None]]


@dataclass
class Page:
    number: int
    width: float
    height: float
    body_top: float = 0.0
    body_bottom: float = 0.0
    lines: list[Line] = field(default_factory=list[Line])
    tables: list[Table] = field(default_factory=list[Table])


@dataclass
class PdfText:
    path: Path
    pages: list[Page]
    toc: dict[str, str] = field(default_factory=dict[str, str])  # "6.10" -> "SR Movement"
    errors: list[str] = field(default_factory=list[str])

    @property
    def lines(self) -> list[Line]:
        return [l for p in self.pages for l in p.lines]

    def page(self, number: int) -> Page:
        return self.pages[number - 1]


def is_real_table(rows: list[list[str | None]]) -> bool:
    # pdfplumber also sees framed text as a table, with one filled cell per row
    filled = [sum(1 for c in r if c and c.strip()) for r in rows]
    return sum(1 for n in filled if n >= 2) >= 2 or any(n >= 3 for n in filled)


def _join_split_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # small caps split a word where the font size changes: "T RAIN" -> "TRAIN"
    out: list[dict[str, Any]] = []
    for w in words:
        if out and w["x0"] - out[-1]["x1"] < 0.5:
            out[-1] = {**out[-1], "text": out[-1]["text"] + w["text"], "x1": w["x1"],
                       "bottom": max(out[-1]["bottom"], w["bottom"]), "size": max(out[-1]["size"], w["size"])}
        else:
            out.append(w)
    return out


def _group_lines(words: list[dict[str, Any]], page_no: int) -> list[Line]:
    rows: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) < LINE_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines: list[Line] = []
    for ws in rows:
        ws.sort(key=lambda w: w["x0"])
        ws = _join_split_words(ws)
        sizes = Counter(round(w["size"], 1) for w in ws)
        bold = sum(len(w["text"]) for w in ws if "bold" in w["fontname"].lower())
        lines.append(Line(
            page=page_no,
            top=min(w["top"] for w in ws),
            bottom=max(w["bottom"] for w in ws),
            x0=ws[0]["x0"],
            x1=max(w["x1"] for w in ws),
            text=" ".join(w["text"] for w in ws),
            size=sizes.most_common(1)[0][0],
            bold=bold > sum(len(w["text"]) for w in ws) / 2,
        ))
    return lines


def _read_page(page: Any, page_no: int) -> Page:
    result = Page(page_no, float(page.width), float(page.height))
    for t in page.find_tables():
        rows = t.extract()
        if is_real_table(rows):
            result.tables.append(Table(tuple(t.bbox), rows))
    words = page.extract_words(extra_attrs=["fontname", "size"])
    result.lines = _group_lines(words, page_no)
    return result


def _margin_key(line: Line, page: Page) -> tuple[str, int, str] | None:
    if line.top < page.height * MARGIN_BAND:
        band = "top"
    elif line.bottom > page.height * (1 - MARGIN_BAND):
        band = "bottom"
    else:
        return None
    return band, round(line.top / 4), re.sub(r"\d+", "#", line.text)


def _remove_margins(pages: list[Page]) -> None:
    # A header or footer is a line that comes back at the same place on many pages
    # (page numbers ignored). A fixed margin doesn't work: X2R5 has text right under its header.
    counts = Counter(k for p in pages for l in p.lines if (k := _margin_key(l, p)))
    needed = max(2, int(len(pages) * REPEAT_RATIO))
    repeated = {k for k, n in counts.items() if n >= needed}
    for p in pages:
        header = [l for l in p.lines if (k := _margin_key(l, p)) and k in repeated and k[0] == "top"]
        footer = [l for l in p.lines if (k := _margin_key(l, p)) and k in repeated and k[0] == "bottom"]
        p.body_top = max((l.bottom for l in header), default=0.0)
        p.body_bottom = min((l.top for l in footer), default=p.height)
        p.lines = [l for l in p.lines if p.body_top < l.top and l.bottom < p.body_bottom]


def rejoin_ids(text: str, id_regex: re.Pattern[str]) -> str:
    """Fix IDs cut by a space, e.g. "REQ-SC_MP _TO_AS" or "REQ -LosTI-"."""
    out: list[str] = []
    for tok in text.split(" "):
        if out and out[-1] and tok:
            prev = out[-1]
            cut = prev[-1] in "-_/" and tok[0].isalnum() or re.match(r"[_\-/]\w", tok)
            joined = (prev + tok).rstrip(".,;:)]")
            if cut and (id_regex.fullmatch(joined) or id_regex.fullmatch(joined + "x")):
                out[-1] = prev + tok
                continue
        out.append(tok)
    return " ".join(out)


def read_toc(pages: list[Page]) -> dict[str, str]:
    # We need the TOC because R2DATO prints its headings in small caps, which come
    # out as "S YS F R EPORT ...". Long entries wrap, with the dots on the second line.
    lines = [l for p in pages for l in p.lines]
    toc: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = TOC_ENTRY_RE.match(line.text)
        if not m and i + 1 < len(lines) and not TOC_RE.search(line.text):
            nxt = lines[i + 1].text
            if TOC_START_RE.match(line.text) and TOC_RE.search(nxt) and not TOC_START_RE.match(nxt):
                m = TOC_ENTRY_RE.match(f"{line.text} {nxt}")
        if m and m.group(1) not in toc:
            toc[m.group(1)] = re.sub(r"\s+", " ", m.group(2)).strip()
    return toc


def _mark_tables(page: Page) -> None:
    for line in page.lines:
        for i, t in enumerate(page.tables):
            if t.bbox[1] - 1 <= line.top and line.bottom <= t.bbox[3] + 1:
                line.table = i
                break


def read_pdf(path: Path, id_regex: re.Pattern[str]) -> PdfText:
    path = Path(path)
    pages: list[Page] = []
    errors: list[str] = []
    with pdfplumber.open(path) as pdf:
        for no, page in enumerate(pdf.pages, start=1):
            try:
                pages.append(_read_page(page, no))
            except Exception as e:  # skip the page, keep going
                msg = f"{path.name} page {no}: cannot be read ({type(e).__name__}: {e})"
                log.error(msg)
                errors.append(msg)
                pages.append(Page(no, float(page.width), float(page.height)))

    _remove_margins(pages)
    toc = read_toc(pages)
    for p in pages:
        p.lines = [l for l in p.lines if not TOC_RE.search(l.text)]
        for l in p.lines:
            l.text = rejoin_ids(l.text, id_regex)
        _mark_tables(p)
    log.info("%s: %d pages, %d lines, %d tables", path.name, len(pages),
             sum(len(p.lines) for p in pages), sum(len(p.tables) for p in pages))
    return PdfText(path, pages, toc, errors)
