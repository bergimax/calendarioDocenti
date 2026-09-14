"""
NLP logic for parsing admin chat messages into structured intents.
Uses Claude API with function calling for intent extraction.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Supported chat intents."""
    MOVE_LESSON = "move_lesson"
    REDUCE_WORKLOAD = "reduce_workload"
    EXCLUDE_DAY = "exclude_day"
    SET_SOFT_CONSTRAINT = "set_soft_constraint"
    ADD_PREFERENCE = "add_preference"
    UNKNOWN = "unknown"


@dataclass
class ParsedIntent:
    """Result of NLP parsing."""
    intent: IntentType
    parameters: Dict[str, Any]
    confidence: float
    clarifications_needed: List[str]
    raw_response: Optional[str] = None


class ChatNLP:
    """
    Parse admin messages into structured intents using pattern matching or Claude API.
    Supports function calling for intent extraction.
    """

    def __init__(self, anthropic_client=None):
        """Initialize with optional Anthropic client."""
        self.client = anthropic_client
        self.supported_intents = [
            IntentType.MOVE_LESSON,
            IntentType.REDUCE_WORKLOAD,
            IntentType.EXCLUDE_DAY,
            IntentType.SET_SOFT_CONSTRAINT,
            IntentType.ADD_PREFERENCE,
        ]

    def parse_message(self, message: str, context: Optional[Dict[str, Any]] = None, use_llm: bool = False) -> ParsedIntent:
        """
        Parse admin message into intent + parameters.

        Args:
            message: Admin's natural language request
            context: Optional context (schedule state, available classes/teachers, etc)
            use_llm: If True and client available, use Claude API with function calling

        Returns:
            ParsedIntent with extracted intent and parameters
        """
        logger.info(f"Parsing message: {message}")

        # Try LLM first if enabled and client available
        if use_llm and self.client:
            try:
                return self._parse_with_llm(message, context)
            except Exception as e:
                logger.warning(f"LLM parsing failed, falling back to patterns: {e}")

        # Pattern matching as fallback
        return self._parse_with_patterns(message, context)

    _DAY_ENUM = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
    _LLM_MODEL = "claude-haiku-4-5-20251001"

    def _llm_tools(self) -> List[Dict[str, Any]]:
        """One tool per supported intent; Claude calls at most one, with
        only the parameters it actually found in the message (no invented
        defaults - the JSON schema's `required` list plus our own
        `_missing_required_params` check below catch anything it leaves
        out, which then becomes a clarification question to the admin)."""
        return [
            {
                "name": IntentType.MOVE_LESSON.value,
                "description": "Sposta una lezione (materia + classe) da un giorno a un altro della settimana corrente.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "description": "Nome della materia, es. 'Matematica'"},
                        "class": {"type": "string", "description": "Nome della classe, es. '1A'"},
                        "from_day": {"type": "string", "enum": self._DAY_ENUM},
                        "to_day": {"type": "string", "enum": self._DAY_ENUM},
                    },
                    "required": ["subject", "class", "from_day", "to_day"],
                },
            },
            {
                "name": IntentType.REDUCE_WORKLOAD.value,
                "description": "Riduce il monte ore settimanale massimo di un docente.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "teacher": {"type": "string", "description": "Nome del docente"},
                        "max_hours": {"type": "integer", "description": "Numero massimo di ore settimanali"},
                    },
                    "required": ["teacher", "max_hours"],
                },
            },
            {
                "name": IntentType.EXCLUDE_DAY.value,
                "description": "Esclude un docente dall'orario in un giorno specifico della settimana.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "teacher": {"type": "string"},
                        "day": {"type": "string", "enum": self._DAY_ENUM},
                    },
                    "required": ["teacher", "day"],
                },
            },
            {
                "name": IntentType.SET_SOFT_CONSTRAINT.value,
                "description": "Imposta un vincolo morbido dell'orario, es. il numero massimo di ore consecutive di teoria.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "constraint_type": {"type": "string", "enum": ["consecutive_hours"]},
                        "subject_type": {"type": "string", "enum": ["TEORIA", "PRATICA"]},
                        "max_hours": {"type": "integer"},
                    },
                    "required": ["constraint_type", "max_hours"],
                },
            },
        ]

    def _missing_required_params(self, intent_type: "IntentType", params: Dict[str, Any]) -> List[str]:
        """Same clarification questions as the pattern-matching path, for
        params Claude left out (it shouldn't, given `required` in the tool
        schema, but a model can still be sloppy)."""
        if intent_type == IntentType.MOVE_LESSON:
            missing = []
            if not params.get("subject"):
                missing.append("Which subject?")
            if not params.get("class"):
                missing.append("Which class?")
            if not params.get("from_day"):
                missing.append("Which day to move from?")
            if not params.get("to_day"):
                missing.append("Which day to move to?")
            return missing
        if intent_type == IntentType.REDUCE_WORKLOAD:
            missing = []
            if not params.get("teacher"):
                missing.append("Which teacher?")
            if params.get("max_hours") is None:
                missing.append("How many hours max?")
            return missing
        if intent_type == IntentType.EXCLUDE_DAY:
            missing = []
            if not params.get("teacher"):
                missing.append("Which teacher?")
            if not params.get("day"):
                missing.append("Which day?")
            return missing
        if intent_type == IntentType.SET_SOFT_CONSTRAINT:
            return ["How many hours?"] if params.get("max_hours") is None else []
        return []

    def _parse_with_llm(self, message: str, context: Optional[Dict[str, Any]] = None) -> ParsedIntent:
        """
        Parse using Claude's tool use (function calling): ask the model to
        call at most one of the 4 intent tools, with only the parameters it
        actually found in the message.
        """
        system = (
            "Sei l'assistente che interpreta le richieste in linguaggio naturale "
            "dell'amministratore scolastico per modificare l'orario settimanale. "
            "Chiama uno dei tool disponibili con i parametri estratti dal messaggio, "
            "usando SOLO valori realmente presenti nel messaggio: non inventare nomi "
            "di materie, classi, docenti o giorni che non sono stati citati. Se la "
            "richiesta non corrisponde a nessuno dei tool disponibili, non chiamare "
            "nessun tool."
        )
        if context:
            system += "\n\nContesto disponibile:\n" + json.dumps(context, ensure_ascii=False)

        response = self.client.messages.create(
            model=self._LLM_MODEL,
            max_tokens=512,
            system=system,
            tools=self._llm_tools(),
            messages=[{"role": "user", "content": message}],
        )

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)

        if not tool_use:
            text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
            return ParsedIntent(
                intent=IntentType.UNKNOWN,
                parameters={},
                confidence=0.0,
                clarifications_needed=[
                    text or "Could you rephrase? I understand: move lesson, reduce workload, "
                    "exclude day, or set constraints."
                ],
                raw_response=text or None,
            )

        intent_type = IntentType(tool_use.name)
        params = dict(tool_use.input)
        clarifications = self._missing_required_params(intent_type, params)

        return ParsedIntent(
            intent=intent_type,
            parameters=params,
            confidence=0.5 if clarifications else 0.95,
            clarifications_needed=clarifications,
            raw_response=json.dumps(params, ensure_ascii=False),
        )

    def _parse_with_patterns(self, message: str, context: Optional[Dict[str, Any]] = None) -> ParsedIntent:
        """
        Fallback pattern-based parsing (no LLM call).
        For v1, use simple string matching.
        """
        msg_lower = message.lower()
        clarifications = []

        # Intent 1: MOVE_LESSON
        # Patterns: "sposta", "move", "trasferisci"
        if any(word in msg_lower for word in ["sposta", "move", "trasferisci"]):
            # Extract subjects, classes, days using simple heuristics
            subject = self._extract_subject(message, context)
            classe = self._extract_class(message, context)
            from_day = self._extract_day(message, context, position="from")
            to_day = self._extract_day(message, context, position="to")

            if not subject:
                clarifications.append("Which subject?")
            if not classe:
                clarifications.append("Which class?")
            if not from_day:
                clarifications.append("Which day to move from?")
            if not to_day:
                clarifications.append("Which day to move to?")

            return ParsedIntent(
                intent=IntentType.MOVE_LESSON,
                parameters={
                    "subject": subject,
                    "class": classe,
                    "from_day": from_day,
                    "to_day": to_day,
                },
                confidence=0.8 if not clarifications else 0.5,
                clarifications_needed=clarifications,
            )

        # Intent 2: REDUCE_WORKLOAD
        # Patterns: "riduci", "reduce", "diminuisci ore"
        if any(word in msg_lower for word in ["riduci", "reduce", "diminuisci", "massimo"]):
            teacher = self._extract_teacher(message, context)
            max_hours = self._extract_number(message)

            if not teacher:
                clarifications.append("Which teacher?")
            if max_hours is None:
                clarifications.append("How many hours max?")

            return ParsedIntent(
                intent=IntentType.REDUCE_WORKLOAD,
                parameters={
                    "teacher": teacher,
                    "max_hours": max_hours,
                },
                confidence=0.8 if not clarifications else 0.5,
                clarifications_needed=clarifications,
            )

        # Intent 3: EXCLUDE_DAY
        # Patterns: "non", "not", "escludere", "exclude"
        if any(word in msg_lower for word in ["non", "not", "escludere", "exclude"]):
            teacher = self._extract_teacher(message, context)
            day = self._extract_day(message, context)

            if not teacher:
                clarifications.append("Which teacher?")
            if not day:
                clarifications.append("Which day?")

            return ParsedIntent(
                intent=IntentType.EXCLUDE_DAY,
                parameters={
                    "teacher": teacher,
                    "day": day,
                },
                confidence=0.8 if not clarifications else 0.5,
                clarifications_needed=clarifications,
            )

        # Intent 4: SET_SOFT_CONSTRAINT
        # Patterns: "massimo", "minimo", "max", "min"
        if any(word in msg_lower for word in ["massimo", "minimo", "max", "min", "consecutive"]):
            # Extract constraint type and value
            if "consecutivo" in msg_lower or "consecutive" in msg_lower:
                constraint_type = "consecutive_hours"
                constraint_value = self._extract_number(message)
                if constraint_value is None:
                    constraint_value = 2  # default

                subject_type = self._extract_subject_type(message, context)

                return ParsedIntent(
                    intent=IntentType.SET_SOFT_CONSTRAINT,
                    parameters={
                        "constraint_type": constraint_type,
                        "subject_type": subject_type,  # TEORIA or PRATICA
                        "max_hours": constraint_value,
                    },
                    confidence=0.7,
                    clarifications_needed=clarifications,
                )

        # Default: UNKNOWN
        return ParsedIntent(
            intent=IntentType.UNKNOWN,
            parameters={},
            confidence=0.0,
            clarifications_needed=[
                "Could you rephrase? I understand: move lesson, reduce workload, exclude day, or set constraints."
            ],
        )

    # ===== Extraction Helpers =====

    def _extract_subject(self, message: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Extract subject name from message."""
        if context and "available_subjects" in context:
            for subject in context["available_subjects"]:
                if subject.lower() in message.lower():
                    return subject
        # Common subjects
        for subject in ["inglese", "matematica", "italiano", "storia", "scienze", "laboratorio"]:
            if subject in message.lower():
                return subject
        return None

    def _extract_class(self, message: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Extract class name (e.g., 2A, 3B)."""
        if context and "available_classes" in context:
            for classe in context["available_classes"]:
                if classe.lower() in message.lower():
                    return classe
        # Pattern: digit + letter (e.g., 2A, 3B)
        import re
        match = re.search(r'\b([1-5][A-Z])\b', message)
        return match.group(1) if match else None

    def _extract_day(self, message: str, context: Optional[Dict[str, Any]] = None, position: str = None) -> Optional[str]:
        """
        Extract day name. When the message mentions two different days (e.g.
        "dal martedi al mercoledi"), `position` picks which one: "from" returns
        the first day mentioned, "to" returns the last (distinct) one mentioned.
        """
        days = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi",
                "monday", "tuesday", "wednesday", "thursday", "friday",
                "lun", "mar", "mer", "gio", "ven"]
        msg_lower = message.lower()

        found = []
        for word in msg_lower.split():
            cleaned = word.strip(".,;:!?")
            for day in days:
                if cleaned == day or cleaned.startswith(day):
                    if not found or found[-1] != day:
                        found.append(day)
                    break

        if not found:
            return None

        if position == "to":
            return found[-1]
        return found[0]

    def _extract_teacher(self, message: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Extract teacher name."""
        if context and "available_teachers" in context:
            for teacher in context["available_teachers"]:
                if teacher.lower() in message.lower():
                    return teacher
        # Look for "Prof.", "Prof", names starting with capital
        import re
        match = re.search(r'(?:Prof\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', message)
        return match.group(1) if match else None

    def _extract_number(self, message: str) -> Optional[int]:
        """Extract integer from message."""
        import re
        match = re.search(r'\b([0-9]+)\b', message)
        return int(match.group(1)) if match else None

    def _extract_subject_type(self, message: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Extract subject type (TEORIA or PRATICA)."""
        msg_lower = message.lower()
        if "teoria" in msg_lower or "theory" in msg_lower:
            return "TEORIA"
        if "pratica" in msg_lower or "practice" in msg_lower:
            return "PRATICA"
        return None

    def validate_intent(self, intent: ParsedIntent, context: Optional[Dict[str, Any]] = None) -> bool:
        """Validate if intent parameters are coherent."""
        if intent.intent == IntentType.UNKNOWN:
            return False

        if intent.intent == IntentType.MOVE_LESSON:
            return bool(
                intent.parameters.get("subject")
                and intent.parameters.get("class")
                and intent.parameters.get("from_day")
                and intent.parameters.get("to_day")
            )

        if intent.intent == IntentType.REDUCE_WORKLOAD:
            return bool(
                intent.parameters.get("teacher")
                and intent.parameters.get("max_hours") is not None
            )

        if intent.intent == IntentType.EXCLUDE_DAY:
            return bool(
                intent.parameters.get("teacher")
                and intent.parameters.get("day")
            )

        return True
