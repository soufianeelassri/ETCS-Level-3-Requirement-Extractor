"""
Every document must match its reference. The other tests pin down the cases
the old scripts got wrong, so they don't come back.
"""

from collections import Counter
import pytest
from conftest import requirements_of
from config import Document
from evaluate import evaluate, read_reference

def test_matches_reference(document: Document) -> None:
    assert document.reference is not None
    ev = evaluate(document.name, requirements_of(document.name), read_reference(document.reference))
    assert ev.false_positives == []
    assert ev.false_negatives == []
    assert ev.errors == []
    assert ev.perfect, ev.summary()

def by_id(name: str, rid: str) -> list:
    return [r for r in requirements_of(name) if r.id == rid]

def test_citation_ending_a_sentence_is_not_a_definition() -> None:
    # p.93 only says "REQ-MA-8.", the real one is on p.97
    [ma8] = by_id("X2R5", "REQ-MA-8")
    assert ma8.page == 97
    assert ma8.traceability == "X2R3 D4.2: REQ-MA-12"

def test_tag_is_not_reused_from_previous_requirement() -> None:
    [ma7] = by_id("X2R5", "REQ-MA-7")
    assert ma7.page == 96
    assert ma7.traceability != "X2R3 D4.2: REQ-MA-6"


@pytest.mark.parametrize("name,rid", [("X2R1", "REQ-Radiohole-1"), ("X2R1", "REQ-LosTI"),
                                      ("X2R5", "REQ-LossComms"), ("R2DATO_V1", "REQ-SC_MP"),
                                      ("R2DATO_V1", "REQ-0016")])
def test_false_requirements_of_old_scripts_not_extracted(name: str, rid: str) -> None:
    assert by_id(name, rid) == []

def test_ids_used_twice_give_two_requirements() -> None:
    counts = Counter(r.id for r in requirements_of("R2DATO_V1"))
    assert counts["REQ-SAFETY"] == 2
    assert counts["REQ-COOP_PENDING"] == 2
    assert [r.page for r in by_id("R2DATO_V1", "REQ-SAFETY")] == [60, 129]
    assert [r.page for r in by_id("R2DATO_V1", "REQ-COOP_PENDING")] == [147, 167]

def test_id_cut_by_a_space_is_rejoined() -> None:
    assert len(by_id("R2DATO_V1", "REQ-SC_MP_TO_AS")) == 1

def test_description_continues_on_next_page_without_header() -> None:
    [r] = by_id("R2DATO_V1", "REQ-SC_SYNTAX")
    assert r.page == 60
    assert "SYNTAX" in r.description and "Interne" not in r.description

def test_definition_after_summary_table() -> None:
    # in a table on p.75, defined on p.78
    [r] = by_id("R2DATO_V1", "REQ-TrainLoc-4")
    assert r.page == 78 and r.description

@pytest.mark.parametrize("rid", ["REQ-TrainLoc-17", "REQ-SC_RB_TO", "REQ-SC_RB_TO_AS", "REQ-SC_MP_TO_AS"])
def test_descriptions_not_empty(rid: str) -> None:
    assert all(r.description for r in by_id("R2DATO_V1", rid))

def test_descriptions_do_not_overlap() -> None:
    [ttd1] = by_id("X2R1", "REQ-TTD-1")
    assert "REQ-TTD-2" not in ttd1.description

@pytest.mark.parametrize("name,rid", [("R2DATO_V1", "REQ-0029"), ("R2DATO_V1", "REQ-TMS-1"),
                                      ("X2R5", "REQ-LossTI-6")])
def test_status_word_after_id_accepted(name: str, rid: str) -> None:
    assert len(by_id(name, rid)) == 1

def test_figures_and_tables() -> None:
    found = {(name, r.id, m.caption.split(":")[0])
             for name in ("X2R1", "X2R3", "X2R5", "R2DATO_V1", "R2DATO_V2")
             for r in requirements_of(name) for m in r.media}
    assert found == {("X2R3", "REQ-TrackStatus-14", "Table 9"), ("X2R3", "REQ-MovSR-1", "Figure 57"),
                     ("X2R5", "REQ-TrackStatus-27", "Table 9"), ("X2R5", "REQ-MovSR-1", "Figure 67"),
                     ("R2DATO_V1", "REQ-TrackStatus-27", "Table 14")}

def test_split_table_is_joined() -> None:
    [r] = by_id("X2R3", "REQ-TrackStatus-14")
    assert [region[0] for region in r.media[0].regions] == [46, 47]

def test_r2dato_v2_chapter_6_only() -> None:
    ids = [r.id for r in requirements_of("R2DATO_V2")]
    assert len(ids) == 41
    assert all(i.startswith(("ADD_", "HDA_", "REG_")) for i in ids)