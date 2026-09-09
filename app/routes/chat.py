from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any
from app.database import get_db
from app.schemas import ChatMessageCreate

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
    """

    async def generate_sse():
        """Generate SSE stream."""
        # Placeholder: yield thinking message
        yield f"data: {__import__('json').dumps({'type': 'thinking', 'text': 'Analizzando richiesta...'})}\n\n"

        # TODO: Implement full chat logic
        # - Parse intent with LLM
        # - Translate to constraints
        # - Call solver with warm start
        # - Yield response events

        # Placeholder: yield ready
        yield f"data: {__import__('json').dumps({'type': 'ready', 'new_score': '81%'})}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


@router.get("/chat/history/{week_start}")
def get_chat_history(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieve chat history for week.
    """
    # TODO: Implement get history logic

    return {
        "messages": [],
    }
