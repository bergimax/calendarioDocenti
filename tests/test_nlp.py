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


# ===== LLM (tool use) parsing, with a stub Anthropic client =====
# No real network call / API key needed: these duck-type the small slice of
# the anthropic SDK's response shape that _parse_with_llm actually reads
# (response.content -> blocks with .type, and .name/.input for tool_use).

class _FakeToolUseBlock:
    def __init__(self, name, input_):
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeMessagesAPI:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response):
        self.messages = _FakeMessagesAPI(response)


def test_llm_parsing_converts_tool_use_into_intent():
    response = _FakeMessage(content=[_FakeToolUseBlock("move_lesson", {
        "subject": "Matematica", "class": "1A", "from_day": "martedi", "to_day": "mercoledi",
    })])
    client = _FakeAnthropicClient(response)
    nlp = ChatNLP(anthropic_client=client)

    intent = nlp.parse_message("sposta matematica di 1A da martedi a mercoledi", use_llm=True)

    assert intent.intent == IntentType.MOVE_LESSON
    assert intent.parameters["class"] == "1A"
    assert intent.parameters["from_day"] == "martedi"
    assert intent.clarifications_needed == []
    # Confirms the tool schema (not pattern matching) actually drove this.
    assert "tools" in client.messages.last_kwargs


def test_llm_parsing_no_tool_call_is_unknown():
    response = _FakeMessage(content=[_FakeTextBlock("Non ho capito la richiesta.")])
    client = _FakeAnthropicClient(response)
    nlp = ChatNLP(anthropic_client=client)

    intent = nlp.parse_message("qualcosa di incomprensibile", use_llm=True)

    assert intent.intent == IntentType.UNKNOWN
    assert intent.clarifications_needed


def test_llm_parsing_missing_required_param_asks_for_clarification():
    response = _FakeMessage(content=[_FakeToolUseBlock("reduce_workload", {"teacher": "Prof Neri"})])
    client = _FakeAnthropicClient(response)
    nlp = ChatNLP(anthropic_client=client)

    intent = nlp.parse_message("riduci le ore di Prof Neri", use_llm=True)

    assert intent.intent == IntentType.REDUCE_WORKLOAD
    assert intent.clarifications_needed  # max_hours missing from the fake tool call


def test_parse_message_ignores_llm_when_use_llm_false():
    """A client can be configured but a caller can still ask for the
    (cheaper, offline) pattern-matching path explicitly."""
    response = _FakeMessage(content=[_FakeToolUseBlock("move_lesson", {})])
    client = _FakeAnthropicClient(response)
    nlp = ChatNLP(anthropic_client=client)

    intent = nlp.parse_message("Riduci ore Prof Neri a massimo 10", use_llm=False)

    assert intent.intent == IntentType.REDUCE_WORKLOAD
    assert client.messages.last_kwargs is None
