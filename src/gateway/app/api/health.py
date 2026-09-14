from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.gateway.app.api.schemas import HealthResponse, ReadinessResponse
from src.gateway.app.config.loader import ConfigError, load_config
from src.gateway.app.core.build_info import get_build_metadata
from src.gateway.app.db.crud import list_request_logs
from src.gateway.app.db.session import get_db

router = APIRouter()


def _database_ok(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/healthz", tags=["health"], response_model=HealthResponse)
async def healthz(request: Request, db: Session = Depends(get_db)):
    database_ok = _database_ok(db)
    recent = list_request_logs(db, datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)) if database_ok else []
    classifier_errors = sum(
        any(signal.get("name") == "classifier_error" for signal in (row.signals or [])) for row in recent
    )
    error_rate = classifier_errors / len(recent) if recent else 0.0
    snapshot = await request.app.state.provider_registry.snapshot()
    providers = [provider.__dict__ for provider in snapshot.providers]
    degraded = not database_ok or error_rate > 0.05 or snapshot.provider_check != "ok"
    return {
        "status": "degraded" if degraded else "ok",
        **get_build_metadata(),
        "db": "ok" if database_ok else "unavailable",
        "classifier_error_rate": error_rate,
        "providers": providers,
    }


@router.get(
    "/readyz",
    tags=["health"],
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A required dependency is unavailable."}},
)
async def readyz(request: Request, db: Session = Depends(get_db)):
    database_ok = _database_ok(db)
    try:
        load_config()
        config_ok = True
    except ConfigError:
        config_ok = False
    snapshot = await request.app.state.provider_registry.snapshot()
    providers_check = snapshot.provider_check
    ready = database_ok and config_ok and providers_check != "unavailable"
    body = {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": "ok" if database_ok else "unavailable",
            "config": "ok" if config_ok else "invalid",
            "providers": providers_check,
        },
    }
    return body if ready else JSONResponse(status_code=503, content=body)
