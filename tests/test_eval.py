"""Test the pure eval scorer (eval.cases.score) — the live run needs a model."""
from __future__ import annotations

from eval.cases import CASES, score


def test_score_fact_and_tool() -> None:
    case = {"q": "x", "must_include": ["pc20", "pc12"], "tool": "get_down_nodes"}
    assert score(case, "PC20 and PC12 are down", ["get_down_nodes"]) == (True, True)
    assert score(case, "only PC20 is down", ["get_down_nodes"]) == (False, True)  # missing pc12
    assert score(case, "PC20 PC12", []) == (True, False)                          # no/wrong tool
    assert score(case, "", []) == (False, False)


def test_cases_are_well_formed() -> None:
    for c in CASES:
        assert c["q"] and c["must_include"] and c["tool"].startswith("get_")
