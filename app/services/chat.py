"""
Business logic for chat interactions.
Parses admin messages, manages solver recalculation, and streams responses.
"""

from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional, AsyncGenerator, List
from app.config import settings
from app.services.schedule import ScheduleService
from app.domain.nlp import ChatNLP, IntentType, ParsedIntent
from app.models import ChatMessage
import logging

logger = logging.getLogger(__name__)


class ChatService:
    """Business logic for chat with AI."""

    def __init__(self, db: Session):
        self.db = db
        self.schedule_service = ScheduleService(db)

        anthropic_client = None
        if settings.ANTHROPIC_API_KEY:
            try:
                import anthropic
                anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            except Exception as e:
                logger.warning(f"Could not initialize Anthropic client, falling back to pattern matching: {e}")

        self.nlp = ChatNLP(anthropic_client=anthropic_client)
        self.use_llm = anthropic_client is not None

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
        1. Parse intent with NLP (Claude tool use if ANTHROPIC_API_KEY is
           configured, pattern matching otherwise)
        2. Validate intent
        3. Resolve the named teacher/class/subject/day into DB ids and
           apply the change for real (move the slot, or re-solve the week
           with the requested extra hard/soft constraint - see
           ScheduleService.move_lesson/exclude_docente_day/
           cap_docente_weekly_hours/set_max_consecutive_teoria)
        4. Yield response events, including the updated schedule
        """
        logger.info(f"Processing chat message: {message}")

        yield {"type": "thinking", "text": "Analizzando richiesta..."}

        try:
            context = self._build_nlp_context(scuola_id)
            intent = self.nlp.parse_message(message, context=context, use_llm=self.use_llm)

            if intent.clarifications_needed:
                yield {
                    "type": "clarification",
                    "text": "Puoi specificare: " + ", ".join(intent.clarifications_needed) + "?",
                    "clarifications": intent.clarifications_needed,
                }
                return

            if not self.nlp.validate_intent(intent):
                yield {
                    "type": "error",
                    "text": "Non riesco a interpretare questa richiesta. Prova a dirmi: 'Sposta [materia] [classe] da [giorno] a [giorno]'",
                }
                return

            yield {"type": "suggestion", "text": f"Ho capito: {self._intent_to_text(intent)}"}

            result = self._apply_intent(scuola_id, week_start, intent)

            if result["status"] == "error":
                yield {"type": "error", "text": result["message"]}
                return

            new_score = result.get("quality_score")
            yield {
                "type": "ready",
                "new_score": new_score,
                "text": (
                    f"Modifiche applicate. Qualità: {new_score:.0f}%"
                    if new_score is not None else "Modifiche applicate."
                ),
                "new_schedule": result,
            }

            self._save_message(scuola_id, schedule_id, "ADMIN", message)
            response_text = f"Ho registrato: {self._intent_to_text(intent)}"
            self._save_message(scuola_id, schedule_id, "AI", response_text)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            yield {
                "type": "error",
                "text": f"Errore: {str(e)}"
            }

    def get_chat_history_for_week(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """Retrieve chat history for the week's schedule; empty if there's no schedule yet."""
        from app.models import OrarioSettimanale

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"messages": []}

        return self.get_chat_history(scuola_id, orario.id)

    def get_chat_history(self, scuola_id: str, schedule_id: str) -> Dict[str, Any]:
        """Retrieve chat history for a specific schedule_id."""
        messages = self.db.query(ChatMessage).filter(
            ChatMessage.scuola_id == scuola_id,
            ChatMessage.orario_settimanale_id == schedule_id,
        ).order_by(ChatMessage.timestamp).all()

        return {
            "messages": [
                {
                    "id": m.id,
                    # DB stores ADMIN/AI; the frontend's ChatMessage type expects lowercase admin/ai.
                    "role": m.ruolo.lower(),
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

    def _apply_intent(self, scuola_id: str, week_start: date, intent: ParsedIntent) -> Dict[str, Any]:
        """
        Resolve the intent's named teacher/class/subject/day into DB ids
        and apply the corresponding real change via ScheduleService,
        rather than the old fake "+2 points" placeholder. Returns
        {"status": "error", "message": ...} or the updated schedule dict
        ({"status": "modified"/"applied", schedule_id, quality_score, slots, ...}).
        """
        params = intent.parameters

        if intent.intent == IntentType.MOVE_LESSON:
            classe_id = self._resolve_classe_id(scuola_id, params["class"])
            materia_id = self._resolve_materia_id(scuola_id, params["subject"])
            if not classe_id:
                return {"status": "error", "message": f"Classe non trovata: {params['class']!r}"}
            if not materia_id:
                return {"status": "error", "message": f"Materia non trovata: {params['subject']!r}"}
            return self.schedule_service.move_lesson(
                scuola_id, week_start, classe_id, materia_id,
                params["from_day"].upper(), params["to_day"].upper(),
            )

        if intent.intent == IntentType.EXCLUDE_DAY:
            docente_id = self._resolve_docente_id(scuola_id, params["teacher"])
            if not docente_id:
                return {"status": "error", "message": f"Docente non trovato: {params['teacher']!r}"}
            return self.schedule_service.exclude_docente_day(
                scuola_id, week_start, docente_id, params["day"].upper(),
            )

        if intent.intent == IntentType.REDUCE_WORKLOAD:
            docente_id = self._resolve_docente_id(scuola_id, params["teacher"])
            if not docente_id:
                return {"status": "error", "message": f"Docente non trovato: {params['teacher']!r}"}
            return self.schedule_service.cap_docente_weekly_hours(
                scuola_id, week_start, docente_id, int(params["max_hours"]),
            )

        if intent.intent == IntentType.SET_SOFT_CONSTRAINT:
            if params.get("subject_type") == "PRATICA":
                return {
                    "status": "error",
                    "message": "Il vincolo su ore consecutive è supportato solo per materie di tipo TEORIA.",
                }
            return self.schedule_service.set_max_consecutive_teoria(
                scuola_id, week_start, int(params["max_hours"]),
            )

        return {"status": "error", "message": "Intent non supportato."}

    def _build_nlp_context(self, scuola_id: str) -> Dict[str, Any]:
        """Names available for this scuola, used both to ground the LLM's
        extraction and by the pattern-matching fallback's own context-aware
        lookups (app/domain/nlp.py's _extract_* helpers)."""
        from app.models import Docente, Classe, Materia

        return {
            "available_teachers": [d.nome for d in self.db.query(Docente).filter_by(scuola_id=scuola_id).all()],
            "available_classes": [c.nome for c in self.db.query(Classe).filter_by(scuola_id=scuola_id).all()],
            "available_subjects": [m.nome for m in self.db.query(Materia).filter_by(scuola_id=scuola_id).all()],
        }

    def _resolve_classe_id(self, scuola_id: str, nome: str) -> Optional[str]:
        from app.models import Classe
        return self._match_by_name(self.db.query(Classe).filter_by(scuola_id=scuola_id).all(), nome)

    def _resolve_materia_id(self, scuola_id: str, nome: str) -> Optional[str]:
        from app.models import Materia
        return self._match_by_name(self.db.query(Materia).filter_by(scuola_id=scuola_id).all(), nome)

    def _resolve_docente_id(self, scuola_id: str, nome: str) -> Optional[str]:
        from app.models import Docente
        return self._match_by_name(self.db.query(Docente).filter_by(scuola_id=scuola_id).all(), nome)

    @staticmethod
    def _match_by_name(rows: List[Any], nome: str) -> Optional[str]:
        """Case-insensitive match: exact first, then substring either way
        (so 'Rossi' matches 'Prof Rossi', and 'matematica' matches
        'Matematica Applicata')."""
        needle = nome.strip().lower()
        for row in rows:
            if row.nome.strip().lower() == needle:
                return row.id
        for row in rows:
            row_lower = row.nome.strip().lower()
            if needle in row_lower or row_lower in needle:
                return row.id
        return None

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
