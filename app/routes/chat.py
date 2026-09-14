from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any
from app.database import get_db
from app.services.chat import ChatService
from app.schemas import ChatMessageCreate
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


@router.post("/chat/send")
async def send_chat_message(
    request: ChatMessageCreate,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Send chat message to AI.
    Returns SSE stream with real-time response.

    Request: {
        "schedule_id": "...",
        "message": "Sposta inglese 2A da martedì a mercoledì"
    }

    Response: SSE stream with events:
    - type: "thinking" → processing message
    - type: "clarification" → need more info
    - type: "suggestion" → parsed intent
    - type: "ready" → new schedule ready
    - type: "error" → error occurred
    """
    scuola_id = _get_current_school_id()

    async def generate_sse():
        """Generate SSE stream."""
        try:
            service = ChatService(db)

            async for event in service.send_message(
                scuola_id=scuola_id,
                schedule_id=request.schedule_id,
                week_start=request.week_start,
                message=request.message,
            ):
                # default=str: the "ready" event's new_schedule carries
                # date/datetime fields (week_start, created_at, ...) that
                # plain json.dumps can't serialize on its own.
                yield f"data: {json.dumps(event, default=str)}\n\n"

        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


@router.get("/chat/history/{week_start}")
def get_chat_history(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieve chat history for the week's schedule (the frontend fetches
    this by week, not by schedule_id - a schedule_id can change across
    weeks but stays stable for a given week after a regenerate, see
    ScheduleRepository.save_generated_schedule).
    """
    scuola_id = _get_current_school_id()

    try:
        service = ChatService(db)
        return service.get_chat_history_for_week(scuola_id=scuola_id, week_start=week_start)

    except Exception as e:
        logger.error(f"Error retrieving chat history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
