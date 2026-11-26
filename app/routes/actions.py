from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app.core.access import not_found, require_owned_file
from app.core.config import get_settings
from app.routes.pages import require_owned_chat
from app.services.analysis_service import AnalysisService
from app.services.chart_service import ChartService
from app.services.file_service import FileReadError, FileService
from app.services.report_service import ReportService


settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))

file_service = FileService(settings)
analysis_service = AnalysisService(file_service)
chart_service = ChartService(file_service, settings)
report_service = ReportService(file_service, settings)

router = APIRouter()
ARTIFACT_NAME = re.compile(
    r"([0-9a-f]{32})__(?:(summary)__[0-9]{14}\.md|[a-z_]+__[0-9]{14}\.(?:png|docx|pdf))"
)


def _panel_context(
    request: Request,
    file_id: str,
    success_message: str | None = None,
    error_message: str | None = None,
):
    stored_file = require_owned_file(request, file_service, file_id)
    preview_context = file_service.build_preview_context(stored_file)
    analysis = analysis_service.analyze(stored_file)
    artifacts = file_service.get_output_artifacts(file_id)
    return {
        "request": request,
        "preview": preview_context,
        "analysis": analysis,
        "artifacts": artifacts,
        "success_message": success_message,
        "error_message": error_message,
    }


@router.post("/actions/analyze/{file_id}")
async def analyze_action(request: Request, file_id: str):
    context = _panel_context(request, file_id, success_message="Анализ обновлен.")
    return templates.TemplateResponse("partials/result_panel.html", context)


@router.post("/actions/chart/{file_id}")
async def chart_action(
    request: Request,
    file_id: str,
    chart_type: str = Form(...),
    x_column: str | None = Form(default=None),
    y_column: str | None = Form(default=None),
):
    try:
        stored_file = require_owned_file(request, file_service, file_id)
        chart_service.generate_chart(stored_file, chart_type, x_column=x_column or None, y_column=y_column or None)
        context = _panel_context(request, file_id, success_message="График построен и сохранен.")
    except FileReadError as exc:
        context = _panel_context(request, file_id, error_message=str(exc))
    return templates.TemplateResponse("partials/result_panel.html", context)


@router.post("/actions/report/{file_id}")
async def report_action(request: Request, file_id: str):
    stored_file = require_owned_file(request, file_service, file_id)
    preview_context = file_service.build_preview_context(stored_file)
    analysis = analysis_service.analyze(stored_file)
    artifacts = file_service.get_output_artifacts(file_id)

    chart_records = artifacts["charts"]
    if not chart_records:
        chart_records = chart_service.generate_default_charts(stored_file)
        artifacts = file_service.get_output_artifacts(file_id)

    report_service.generate_report(stored_file, analysis, chart_records[:3], preview_context)
    context = _panel_context(request, file_id, success_message="DOCX-отчет сформирован и готов к скачиванию.")
    return templates.TemplateResponse("partials/result_panel.html", context)


def owned_artifact_path(request: Request, artifact_name: str) -> Path:
    match = ARTIFACT_NAME.fullmatch(artifact_name)
    if not match:
        raise not_found()
    resource_id, is_summary = match.groups()
    if is_summary:
        require_owned_chat(request, resource_id)
    else:
        require_owned_file(request, file_service, resource_id)

    candidate = settings.output_dir / artifact_name
    if candidate.is_symlink() or not candidate.is_file():
        raise not_found()
    return candidate


@router.get("/download/{artifact_name}")
async def download_artifact(request: Request, artifact_name: str):
    candidate = owned_artifact_path(request, artifact_name)
    return FileResponse(path=candidate, filename=candidate.name)


@router.get("/storage/outputs/{artifact_name}")
async def preview_artifact(request: Request, artifact_name: str):
    candidate = owned_artifact_path(request, artifact_name)
    if candidate.suffix != ".png":
        return FileResponse(path=candidate, filename=candidate.name)
    return FileResponse(path=candidate, media_type="image/png")


@router.get("/storage/uploads/{saved_name}")
async def serve_upload(request: Request, saved_name: str):
    stored_file = require_owned_file(request, file_service, saved_name.partition("_")[0])
    if stored_file.saved_name != saved_name:
        raise not_found()
    if stored_file.kind == "image":
        media_type = mimetypes.guess_type(stored_file.path.name)[0] or "application/octet-stream"
        return FileResponse(path=stored_file.path, media_type=media_type)
    return FileResponse(path=stored_file.path, filename=stored_file.original_name)
