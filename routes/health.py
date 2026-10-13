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

    Postgres only, deliberately. Redis is checked nowhere: a cache outage
    degrades latency, not correctness, because url_cache swallows RedisError
    and every lookup falls through to Postgres. Readiness is what the load
    balancer uses to decide whether to send traffic, so failing it on Redis
    would take every task out of service at once - the cache is shared, so all
    of them would fail together - and turn a slower service into no service.
    Postgres is different: a redirect cannot be served without it, since even
    a cache hit still records the click, so it belongs here.
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.rollback()
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", database="unreachable")
    return ReadyResponse(status="ok", database="ok")
