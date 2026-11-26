from __future__ import annotations

import re
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import HTTPException, Request, Response

from app.services.file_service import FileReadError, FileService, StoredFile


SESSION_COOKIE = "data_assistant_session"
RESOURCE_ID = re.compile(r"[0-9a-f]{32}")
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def session_token(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE, "")
    return token if SESSION_TOKEN.fullmatch(token) else ""


def new_or_existing_session(request: Request) -> str:
    return session_token(request) or token_urlsafe(32)


def owner_id(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest() if token else ""


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    if not session_token(request):
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=365 * 24 * 60 * 60,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
        )


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Ресурс не найден.")


def require_owned_file(request: Request, file_service: FileService, file_id: str) -> StoredFile:
    owner = owner_id(session_token(request))
    if not owner or not RESOURCE_ID.fullmatch(file_id):
        raise not_found()

    try:
        stored_file = file_service.get_file(file_id)
    except FileReadError as exc:
        raise not_found() from exc

    if (
        stored_file.owner_id != owner
        or stored_file.path.is_symlink()
        or not stored_file.path.is_file()
        or stored_file.path.resolve().parent != file_service.settings.upload_dir.resolve()
    ):
        raise not_found()
    return stored_file
