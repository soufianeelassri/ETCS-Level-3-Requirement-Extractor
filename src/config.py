"""
Step 1: Settings, from config.toml or a pdf/output/version on the command line.
"""

import argparse
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.toml"
VERSIONS = ("X2R1", "X2R3", "X2R5", "R2DATO")

class ConfigError(Exception):
    pass

@dataclass(frozen=True)
class Document:
    name: str
    pdf: Path
    output: Path
    version: str
    reference: Path | None = None

@dataclass(frozen=True)
class Config:
    documents: list[Document]
    id_patterns: list[str]

    @property
    def id_regex(self) -> re.Pattern[str]:
        return re.compile("|".join(f"(?:{p})" for p in self.id_patterns))

def _document(entry: dict, base: Path, index: int) -> Document:
    missing = [k for k in ("name", "pdf", "output", "version") if not entry.get(k)]
    if missing:
        raise ConfigError(f"documents[{index}]: missing {', '.join(missing)}")
    version = entry["version"].upper()
    if version not in VERSIONS:
        raise ConfigError(f"{entry['name']}: version '{entry['version']}' unknown, expected one of {VERSIONS}")
    reference = base / entry["reference"] if entry.get("reference") else None
    return Document(entry["name"], base / entry["pdf"], base / entry["output"], version, reference)

def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"settings file not found: {path}")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: {e}") from e

    patterns = data.get("ids", {}).get("patterns", [])
    if not patterns:
        raise ConfigError(f"{path.name}: [ids] patterns is empty")
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            raise ConfigError(f"{path.name}: invalid identifier pattern {p!r}: {e}") from e

    documents = [_document(d, path.parent, i) for i, d in enumerate(data.get("documents", []))]
    if not documents:
        raise ConfigError(f"{path.name}: no [[documents]] block")
    names = [d.name for d in documents]
    if len(set(names)) != len(names):
        raise ConfigError(f"{path.name}: two documents share the same name")
    return Config(documents, patterns)

def from_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Extract requirements from specification PDFs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="settings file (default: config.toml)")
    parser.add_argument("args", nargs="*",
                        help="document names from the settings file, or <pdf> <output> <version>")
    ns = parser.parse_args(argv)
    config = load_config(ns.config)

    if len(ns.args) == 3 and ns.args[0].lower().endswith(".pdf"):
        pdf, output, version = ns.args
        doc = _document({"name": Path(pdf).stem, "pdf": pdf, "output": output, "version": version},
                        Path.cwd(), 0)
        return Config([doc], config.id_patterns)

    if ns.args:
        by_name = {d.name.lower(): d for d in config.documents}
        unknown = [a for a in ns.args if a.lower() not in by_name]
        if unknown:
            raise ConfigError(f"unknown document(s) {', '.join(unknown)}; "
                              f"known: {', '.join(d.name for d in config.documents)}")
        return Config([by_name[a.lower()] for a in ns.args], config.id_patterns)
    return config

def check_files(config: Config) -> None:
    missing = [str(d.pdf) for d in config.documents if not d.pdf.is_file()]
    missing += [str(d.reference) for d in config.documents if d.reference and not d.reference.is_file()]
    if missing:
        raise ConfigError("file(s) not found:\n  " + "\n  ".join(missing))