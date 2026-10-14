"""
Step 3: Find where each requirement is defined (not just cited).
"""

import re
from dataclasses import dataclass
from reader import Line, PdfText

SECTION = r"\d+(?:\.\d+)+\s"
# no longer ID right after (REQ-SC_MP vs REQ-SC_MP_TO_AS), and not "REQ-MA-8." ending a sentence
AFTER_ID = r"(?=\s|\[|\(|:|$)(?!\s*[.,;])"

@dataclass
class Definition:
    id: str
    page: int
    line: Line
    rest: str  # what follows the ID on its line, e.g. "Mandatory [X2R3 D4.2: REQ-MA-12]"
    row: list[str] | None = None  # table layout only
    table: int | None = None
    row_index: int | None = None

def _text_definitions(doc: PdfText, id_regex: re.Pattern[str]) -> list[Definition]:
    # Lines inside tables are skipped: summary tables only cite requirements
    # (REQ-TrainLoc-4 is in a table on R2DATO V1 p.75 but defined p.78).
    start = re.compile(rf"^({id_regex.pattern}){AFTER_ID}")
    found: list[Definition] = []
    for page in doc.pages:
        for i, line in enumerate(page.lines):
            if line.table is not None:
                continue
            m = start.match(line.text)
            if m and not (i and _continues_sentence(page.lines[i - 1], line)):
                found.append(Definition(m.group(1), line.page, line, line.text[m.end(1):].strip()))
    return found

def _continues_sentence(prev: Line, line: Line) -> bool:
    # "...the mechanism in / REQ-LossTI-2 and REQ-LossTI-3 is applied." (X2R5 p.126)
    # is a citation that happens to wrap at the start of a line.
    return (abs(prev.x0 - line.x0) < 2 and line.top - prev.bottom < 8
            and not prev.text.rstrip().endswith((".", ":", ";", "!", "?", ")"))
            and not re.match(SECTION, prev.text))

def _table_definitions(doc: PdfText, id_regex: re.Pattern[str]) -> list[Definition]:
    found: list[Definition] = []
    for page in doc.pages:
        for t_index, table in enumerate(page.tables):
            for r_index, row in enumerate(table.rows):
                cells = [(c or "").strip() for c in row]
                filled = [c for c in cells if c]
                if not filled:
                    continue
                rid = re.sub(r"\s+", "", filled[0])
                if not id_regex.fullmatch(rid):
                    continue
                # a requirement row is the ID and one sentence; summary tables (R2DATO V1
                # p.127) have only IDs, the review table (p.194) has 4-5 short cells
                if len(filled) != 2 or len(filled[1].split()) < 5:
                    continue
                line = next((l for l in page.lines if l.table == t_index and l.text.startswith(rid)), None)
                if line is None:
                    line = Line(page.number, table.bbox[1], table.bbox[1], table.bbox[0], table.bbox[2],
                                rid, 0.0, False, t_index)
                found.append(Definition(rid, page.number, line, " ".join(filled[1:]), filled, t_index, r_index))
    return found

def find_definitions(doc: PdfText, id_regex: re.Pattern[str]) -> list[Definition]:
    # No dedup on purpose: REQ-SAFETY and REQ-COOP_PENDING are each used for two
    # different requirements in R2DATO V1.
    found = _text_definitions(doc, id_regex)
    in_text = {d.id for d in found}
    found += [d for d in _table_definitions(doc, id_regex) if d.id not in in_text]
    found.sort(key=lambda d: (d.page, d.line.top))
    return found