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
            # Create service
            service = ChatService(db)

            # Get schedule to extract week_start
            # TODO: Extract from schedule_id or pass as parameter
            week_start = date.today()  # Placeholder

            # Process message and yield events
            async for event in service.send_message(
                scuola_id=scuola_id,
                schedule_id=request.schedule_id,
                week_start=week_start,
                message=request.message,
            ):
                # Format as SSE
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            logger.error(f"Error in chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


@router.get("/chat/history/{schedule_id}")
def get_chat_history(
    schedule_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieve chat history for schedule.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ChatService(db)
        result = service.get_chat_history(
            scuola_id=scuola_id,
            schedule_id=schedule_id,
        )
        return result

    except Exception as e:
        logger.error(f"Error retrieving chat history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
