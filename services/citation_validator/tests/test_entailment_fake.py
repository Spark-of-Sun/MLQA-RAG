from __future__ import annotations

from app.entailment_check import WordOverlapEntailmentChecker, get_entailment_checker


def test_get_entailment_checker_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("ENTAILMENT_BACKEND", raising=False)
    assert isinstance(get_entailment_checker(), WordOverlapEntailmentChecker)


def test_fake_checker_full_overlap_scores_1():
    checker = WordOverlapEntailmentChecker()
    score = checker.score("the term is 12 months", "the term is 12 months and nothing else")
    assert score == 1.0


def test_fake_checker_no_overlap_scores_0():
    checker = WordOverlapEntailmentChecker()
    score = checker.score("completely unrelated claim about dogs", "the term is 12 months")
    assert score == 0.0


def test_fake_checker_partial_overlap_is_between_0_and_1():
    checker = WordOverlapEntailmentChecker()
    score = checker.score("the term is 99 months", "the term is 12 months")
    assert 0.0 < score < 1.0
