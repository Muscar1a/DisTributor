"""Explicit contracts for OpenAI endpoints outside SmartRoute's supported subset."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from src.gateway.app.api.errors import openai_error_response
from src.gateway.app.api.schemas import ErrorEnvelope

router = APIRouter()


def _unsupported_endpoint(request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    endpoint = request.url.path
    return openai_error_response(
        status_code=404,
        request_id=request_id,
        message=f"The endpoint '{endpoint}' is not supported by SmartRoute's text-only API subset.",
        error_type="invalid_request_error",
        code="unsupported_endpoint",
        details={"endpoint": endpoint, "capability": "text_chat_completions_only"},
    )


_UNSUPPORTED_RESPONSE = {
    404: {
        "model": ErrorEnvelope,
        "description": "The OpenAI endpoint is outside SmartRoute's supported text-only subset.",
    }
}


@router.post("/responses", tags=["compatibility"], status_code=404, responses=_UNSUPPORTED_RESPONSE)
async def unsupported_responses(request: Request):
    return _unsupported_endpoint(request)


@router.post("/embeddings", tags=["compatibility"], status_code=404, responses=_UNSUPPORTED_RESPONSE)
async def unsupported_embeddings(request: Request):
    return _unsupported_endpoint(request)


@router.post("/images/generations", tags=["compatibility"], status_code=404, responses=_UNSUPPORTED_RESPONSE)
async def unsupported_image_generations(request: Request):
    return _unsupported_endpoint(request)


@router.post("/audio/transcriptions", tags=["compatibility"], status_code=404, responses=_UNSUPPORTED_RESPONSE)
async def unsupported_audio_transcriptions(request: Request):
    return _unsupported_endpoint(request)
