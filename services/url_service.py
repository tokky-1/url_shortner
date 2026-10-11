
from sqlalchemy.orm import Session

from core.codec import decode, encode
from core.exceptions import URLNotFoundError
from repository.url_repository import create, get_by_id, increment_clicks

_MAX_URL_ID = 2**63 - 1


def create_short_url(db: Session, original_url: str) -> str:
   
    url = create(db, original_url)
    return encode(url.id)


def resolve(db: Session, code: str) -> str:
    try:
        url_id = decode(code)
    except ValueError as exc:
       
        raise URLNotFoundError(code) from exc

    if not 0 <= url_id <= _MAX_URL_ID:
        raise URLNotFoundError(code)

    if encode(url_id) != code:
        raise URLNotFoundError(code)

    url = get_by_id(db, url_id)
    if url is None:
        raise URLNotFoundError(code)

    increment_clicks(db, url_id)
    return url.original_url
