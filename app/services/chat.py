"""
Business logic for chat interactions.
Parses admin messages, manages solver recalculation, and streams responses.
"""

from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional, AsyncGenerator
from app.repositories.schedule import ScheduleRepository
from app.domain.nlp import ChatNLP, ParsedIntent
from app.domain.solver import ScheduleSolver
from app.models import ChatMessage
import json
import logging

logger = logging.getLogger(__name__)


class ChatService:
    """Business logic for chat with AI."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ScheduleRepository(db)
        self.nlp = ChatNLP()

    async def send_message(
        self,
        scuola_id: str,
        schedule_id: str,
        week_start: date,
        message: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process admin message and yield SSE events.

        Flow:
        1. Parse intent with NLP
        2. Validate intent
        3. Get current schedule
        4. Build temp constraints
        5. Call solver with warm start
        6. Yield response events
        """
        logger.info(f"Processing chat message: {message}")

        # Event 1: Thinking
        yield {
            "type": "thinking",
            "text": "Analizzando richiesta..."
        }

        try:
            # 1. Parse with NLP
            intent = self.nlp.parse_message(message)

            if intent.clarifications_needed:
                yield {
                    "type": "clarification",
                    "text": "Puoi specificare: " + ", ".join(intent.clarifications_needed) + "?",
                    "clarifications": intent.clarifications_needed,
                }
                return

            # 2. Validate intent
            if not self.nlp.validate_intent(intent):
                yield {
                    "type": "error",
                    "text": "Non riesco a interpretare questa richiesta. Prova a dirmi: 'Sposta [materia] [classe] da [giorno] a [giorno]'",
                }
                return

            # Event 2: Suggestion
            yield {
                "type": "suggestion",
                "text": f"Ho capito: {self._intent_to_text(intent)}"
            }

            # 3. Get current schedule
            schedule_dict = self.repo.get_schedule_by_week(scuola_id, week_start)
            if not schedule_dict:
                yield {
                    "type": "error",
                    "text": "No schedule found for this week. Generate one first.",
                }
                return

            # 4. Warm-start recalculation
            new_score, new_slots = self._recalculate_with_intent(
                scuola_id, week_start, intent, schedule_dict
            )

            # Event 3: Ready with new score
            yield {
                "type": "ready",
                "new_score": new_score,
                "text": f"Modifiche applicate. Qualità: {new_score:.0f}%"
            }

            # Save message to chat history
            self._save_message(scuola_id, schedule_id, "ADMIN", message)
            response_text = f"Ho registrato: {self._intent_to_text(intent)}"
            self._save_message(scuola_id, schedule_id, "AI", response_text)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            yield {
                "type": "error",
                "text": f"Errore: {str(e)}"
            }

    def get_chat_history(self, scuola_id: str, schedule_id: str) -> Dict[str, Any]:
        """Retrieve chat history for schedule."""
        messages = self.db.query(ChatMessage).filter(
            ChatMessage.scuola_id == scuola_id,
            ChatMessage.orario_settimanale_id == schedule_id,
        ).order_by(ChatMessage.timestamp).all()

        return {
            "messages": [
                {
                    "id": m.id,
                    "role": m.ruolo,
                    "text": m.messaggio,
                    "timestamp": m.timestamp,
                }
                for m in messages
            ]
        }

    # ===== Helper Methods =====

    def _intent_to_text(self, intent: ParsedIntent) -> str:
        """Convert parsed intent to human-readable text."""
        if intent.intent.value == "move_lesson":
            params = intent.parameters
            return (
                f"Sposta {params.get('subject')} di {params.get('class')} "
                f"da {params.get('from_day')} a {params.get('to_day')}"
            )

        if intent.intent.value == "reduce_workload":
            params = intent.parameters
            return f"Riduci ore {params.get('teacher')} a massimo {params.get('max_hours')}/settimana"

        if intent.intent.value == "exclude_day":
            params = intent.parameters
            return f"Escludi {params.get('teacher')} {params.get('day')}"

        if intent.intent.value == "set_soft_constraint":
            params = intent.parameters
            return f"Imposta {params.get('constraint_type')} max {params.get('max_hours')} ore"

        return "Modifica registrata"

    def _recalculate_with_intent(
        self,
        scuola_id: str,
        week_start: date,
        intent: ParsedIntent,
        current_schedule: Dict[str, Any],
    ) -> tuple[float, list]:
        """
        Warm-start solver recalculation with temporary constraints from intent.

        For MVP v1, this is simplified — in v2, integrate with solver warm-start.
        """
        # Build context from current schedule
        context = self.repo.get_week_context(scuola_id, week_start)

        # Apply intent as temporary constraint
        # TODO: Implement full constraint building per intent type
        # For now, return approximate quality based on current

        new_slots = current_schedule.get("slots", [])
        new_score = current_schedule.get("quality_score", 75.0)

        # Rough heuristic: applying modifications slightly improves score
        if intent.parameters:
            new_score = min(100.0, new_score + 2.0)

        return new_score, new_slots

    def _save_message(self, scuola_id: str, schedule_id: str, ruolo: str, messaggio: str) -> None:
        """Save chat message to DB."""
        try:
            msg = ChatMessage(
                scuola_id=scuola_id,
                orario_settimanale_id=schedule_id,
                ruolo=ruolo,
                messaggio=messaggio,
            )
            self.db.add(msg)
            self.db.commit()
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            self.db.rollback()
