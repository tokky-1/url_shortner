from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from db.connect import get_db
from schemas.url import HealthResponse,ReadyResponse

health_router = APIRouter()

@health_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is up. Touches nothing."""
    return HealthResponse(status="ok")


@health_router.get("/ready", response_model=ReadyResponse)
def ready(response: Response, db: Session = Depends(get_db)) -> ReadyResponse:
    """Readiness: can we actually serve traffic?

    Returns 503 rather than raising HTTPException, keeping HTTPException to
    the single spot where a domain error is translated.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.rollback()
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", database="unreachable")
    return ReadyResponse(status="ok", database="ok")
