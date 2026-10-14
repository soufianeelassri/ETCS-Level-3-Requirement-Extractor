"""
Step 6: Compare an extraction with the manual reference: match on ID, then check topic, description (90 % similar), traceability and figures/tables.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import openpyxl
from describer import Requirement

DESCRIPTION_THRESHOLD = 0.90

@dataclass
class RefRow:
    topic: str
    id: str
    description: str
    traceability: str
    has_media: bool

@dataclass
class Evaluation:
    document: str
    extracted: int
    reference: int
    tp: int
    false_positives: list[str]
    false_negatives: list[str]
    topic_ok: int
    description_ok: int
    traceability_ok: int
    media_ok: int
    errors: list[str] = field(default_factory=list[str])

    @property
    def precision(self) -> float:
        return self.tp / self.extracted if self.extracted else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.reference if self.reference else 0.0

    def rate(self, ok: int) -> float:
        return ok / self.tp if self.tp else 0.0

    @property
    def perfect(self) -> bool:
        return self.precision == self.recall == 1.0 and \
            self.topic_ok == self.description_ok == self.traceability_ok == self.media_ok == self.tp

    def summary(self) -> str:
        return (f"{self.document}: {self.extracted} extracted / {self.reference} in reference, "
                f"precision {self.precision:.3f}, recall {self.recall:.3f}, "
                f"topic {self.rate(self.topic_ok):.1%}, description {self.rate(self.description_ok):.1%}, "
                f"traceability {self.rate(self.traceability_ok):.1%}, figures/tables {self.rate(self.media_ok):.1%}")

def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()

def read_reference(path: Path) -> list[RefRow]:
    wb = openpyxl.load_workbook(path)
    ws = wb["Requirements"]
    with_media = {img.anchor._from.row + 1 for img in ws._images}  # pyright: ignore
    rows: list[RefRow] = []
    for r in ws.iter_rows(min_row=2):
        if r[1].value:
            rows.append(RefRow(str(r[0].value or "").strip(), str(r[1].value).strip(), str(r[2].value or ""),
                               str(r[3].value or "").strip(), r[0].row in with_media))
    return rows

def evaluate(name: str, requirements: list[Requirement], reference: list[RefRow]) -> Evaluation:
    # an ID used twice (REQ-SAFETY) is matched in document order
    pending: dict[str, list[RefRow]] = defaultdict(list)
    for row in reference:
        pending[row.id].append(row)
    ev = Evaluation(name, len(requirements), len(reference), 0, [], [], 0, 0, 0, 0)
    for r in requirements:
        if not pending[r.id]:
            ev.false_positives.append(r.id)
            continue
        ref = pending[r.id].pop(0)
        ev.tp += 1
        if r.topic == ref.topic:
            ev.topic_ok += 1
        else:
            ev.errors.append(f"{r.id} p.{r.page} topic: {r.topic!r}, expected {ref.topic!r}")
        ratio = similarity(r.description, ref.description)
        if ratio >= DESCRIPTION_THRESHOLD:
            ev.description_ok += 1
        else:
            ev.errors.append(f"{r.id} p.{r.page} description {ratio:.0%} identical: "
                             f"{normalise(r.description)[:80]!r}, expected {normalise(ref.description)[:80]!r}")
        if r.traceability == ref.traceability:
            ev.traceability_ok += 1
        else:
            ev.errors.append(f"{r.id} p.{r.page} traceability: {r.traceability!r}, expected {ref.traceability!r}")
        if bool(r.media) == ref.has_media:
            ev.media_ok += 1
        else:
            ev.errors.append(f"{r.id} p.{r.page} figures/tables: {len(r.media)}, expected "
                             f"{'one' if ref.has_media else 'none'}")
    ev.false_negatives = [row.id for rows in pending.values() for row in rows]
    return ev