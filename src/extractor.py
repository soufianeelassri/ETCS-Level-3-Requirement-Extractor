"""
Extract the requirements of the documents listed in config.toml.
    python src/extractor.py                            every document
    python src/extractor.py X2R3 R2DATO_V1             only these
    python src/extractor.py <pdf> <output> <version>   a single PDF
Results go to output/, problems to output/extractor.log.
"""

import logging
import sys
import time
from config import Config, ConfigError, Document, check_files, from_args
from describer import Requirement, describe
from evaluate import Evaluation, evaluate, read_reference
from finder import find_definitions
from reader import read_pdf
from tracer import traceability
from writer import write_requirements

log = logging.getLogger("extractor")

def setup_logging(config: Config) -> None:
    log_file = config.documents[0].output.parent / "extractor.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    console.setLevel(logging.INFO)
    # not DEBUG: pdfminer would fill the log with hundreds of MB
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console], force=True)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    log.info("log file: %s", log_file)

def extract(doc: Document, config: Config) -> list[Requirement]:
    pdf = read_pdf(doc.pdf, config.id_regex)
    definitions = find_definitions(pdf, config.id_regex)
    requirements = describe(pdf, definitions)
    for r in requirements:
        assert r.definition is not None
        r.traceability = traceability(r.definition)
        if not r.description and not r.media:
            log.warning("%s: %s (p.%d) has no description", doc.name, r.id, r.page)
        if not r.topic:
            log.warning("%s: %s (p.%d) has no topic", doc.name, r.id, r.page)
    return requirements

def run_document(doc: Document, config: Config) -> Evaluation | None:
    start = time.time()
    log.info("== %s (%s)", doc.name, doc.pdf.name)
    requirements = extract(doc, config)
    images = write_requirements(requirements, doc.pdf, doc.output)
    log.info("   %d requirements, %d figures/tables -> %s (%.0f s)",
             len(requirements), images, doc.output.name, time.time() - start)
    if doc.reference is None:
        return None
    ev = evaluate(doc.name, requirements, read_reference(doc.reference))
    for line in ev.errors:
        log.warning("%s: %s", doc.name, line)
    for rid in ev.false_positives:
        log.warning("%s: %s extracted but not in the reference", doc.name, rid)
    for rid in ev.false_negatives:
        log.warning("%s: %s in the reference but not extracted", doc.name, rid)
    return ev

def main(argv: list[str] | None = None) -> int:
    try:
        config = from_args(argv)
        check_files(config)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    setup_logging(config)

    evaluations: list[Evaluation] = []
    failed: list[str] = []
    for doc in config.documents:
        try:
            ev = run_document(doc, config)
            if ev:
                evaluations.append(ev)
        except Exception:  # log it and go on with the next document
            log.exception("%s: extraction failed", doc.name)
            failed.append(doc.name)

    if evaluations:
        log.info("\n== Comparison with the manual reference")
        for ev in evaluations:
            log.info("%s %s", "OK  " if ev.perfect else "DIFF", ev.summary())
    if failed:
        log.error("failed: %s", ", ".join(failed))
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())