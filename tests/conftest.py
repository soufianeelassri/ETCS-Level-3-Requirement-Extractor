import sys
from functools import cache
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import Document, load_config  # noqa: E402
from describer import Requirement  # noqa: E402
from extractor import extract  # noqa: E402

CONFIG = load_config()

@cache  # each PDF is read once for the whole test run
def requirements_of(name: str) -> list[Requirement]:
    doc = next(d for d in CONFIG.documents if d.name == name)
    return extract(doc, CONFIG)

@pytest.fixture(params=[d.name for d in CONFIG.documents])
def document(request: pytest.FixtureRequest) -> Document:
    return next(d for d in CONFIG.documents if d.name == request.param)