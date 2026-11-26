from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.core.access import not_found, require_owned_file
from app.routes.pages import chat_service, file_service, render_page, require_owned_chat

router = APIRouter()


@router.post("/chat/{conversation_id}/message")
async def send_message(
    request: Request,
    conversation_id: str,
    message_text: str = Form(default=""),
    data_file: UploadFile | None = File(default=None),
):
    conversation = require_owned_chat(request, conversation_id)
    conversation = await chat_service.process_turn(conversation, message_text, data_file)

    return render_page(
        request,
        "chat.html",
        "partials/chat_shell.html",
        chat_service.build_page_context(request, conversation),
    )


@router.post("/chat/{conversation_id}/activate/{file_id}")
async def activate_file(request: Request, conversation_id: str, file_id: str):
    conversation = require_owned_chat(request, conversation_id)
    if not any(record["file_id"] == file_id for record in conversation["files"]):
        raise not_found()
    require_owned_file(request, file_service, file_id)
    conversation = chat_service.activate_file(conversation, file_id)

    return render_page(
        request,
        "chat.html",
        "partials/chat_shell.html",
        chat_service.build_page_context(request, conversation),
    )
