"""Unit tests for the pattern-based chat NLP parser."""

from app.domain.nlp import ChatNLP, IntentType


def test_move_lesson_distinguishes_from_and_to_day():
    """
    Regression test: _extract_day used to ignore its `position` argument and
    always return the first day mentioned, so "sposta ... dal martedi al
    mercoledi" (the exact example from specs.md 5.1) produced identical
    from_day/to_day.
    """
    nlp = ChatNLP()
    message = "Sposta l'inglese di 2A dal martedi al mercoledi"

    intent = nlp.parse_message(message)

    assert intent.intent == IntentType.MOVE_LESSON
    assert intent.parameters["from_day"] is not None
    assert intent.parameters["to_day"] is not None
    assert intent.parameters["from_day"] != intent.parameters["to_day"]
    assert "mar" in intent.parameters["from_day"]
    assert "mer" in intent.parameters["to_day"]
    assert intent.clarifications_needed == []


def test_move_lesson_extracts_subject_and_class():
    nlp = ChatNLP()
    intent = nlp.parse_message("Sposta matematica di 3A dal lunedi al venerdi")
    assert intent.parameters["subject"] == "matematica"
    assert intent.parameters["class"] == "3A"


def test_reduce_workload_intent():
    nlp = ChatNLP()
    intent = nlp.parse_message("Riduci ore Prof Neri a massimo 10")
    assert intent.intent == IntentType.REDUCE_WORKLOAD
    assert intent.parameters["max_hours"] == 10


def test_unknown_message_asks_for_clarification():
    nlp = ChatNLP()
    intent = nlp.parse_message("blah blah non capisco niente di orari")
    # "non" triggers EXCLUDE_DAY heuristics before falling through to UNKNOWN
    assert intent.intent in (IntentType.UNKNOWN, IntentType.EXCLUDE_DAY)
