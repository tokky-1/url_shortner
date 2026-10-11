from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.exceptions import URLNotFoundError
from db.connect import get_db
from schemas.url import (ShortenRequest,ShortenResponse,)
from services.url_service import create_short_url, resolve

router = APIRouter()


@router.post("/urls",status_code=status.HTTP_201_CREATED,response_model=ShortenResponse,)
def shorten(payload: ShortenRequest,db: Session = Depends(get_db),settings: Settings = Depends(get_settings),) -> ShortenResponse:
    code = create_short_url(db, str(payload.url))
    return ShortenResponse(code=code, short_url=settings.short_url(code))

@router.get("/{code}")
def redirect_to_original(code: str,db: Session = Depends(get_db),) -> RedirectResponse:
    try:
        original_url = resolve(db, code)
    except URLNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="short code not found",
        )
    return RedirectResponse(original_url, status_code=302)
