"""
Step 5: Traceability, read from the brackets after the ID.
    REQ-MA-8 Mandatory [X2R3 D4.2: REQ-MA-12]  ->  "X2R3 D4.2: REQ-MA-12"
No brackets means no traceability.
"""

import re
from finder import Definition

TAG_RE = re.compile(r"\[+\s*([^\[\]]*?)\s*\]+")  # X2R3 p.52 has "[New Requirement]]"


def traceability(d: Definition) -> str:
    if d.row is not None:
        return ""  # R2DATO V2 tables have no traceability column
    m = TAG_RE.search(d.rest)
    return m.group(1) if m else ""