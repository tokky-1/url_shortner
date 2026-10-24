from sqlalchemy.orm import Session

from cache import url_cache
from core.codec import decode, encode
from core.exceptions import URLNotFoundError
from repository.url_repository import create, get_by_id, increment_clicks

_MAX_URL_ID = 2**63 - 1


def create_short_url(db: Session, original_url: str) -> str:
    url = create(db, original_url)
    return encode(url.id)


def resolve(db: Session, code: str) -> str:
    """Resolve a short code to its destination, counting the click.

    The cache sits here rather than in the route or the repository: this is the
    only layer that knows a lookup can come from either Redis or Postgres.
    """
    try:
        url_id = decode(code)
    except ValueError as exc:
        raise URLNotFoundError(code) from exc

    if not 0 <= url_id <= _MAX_URL_ID:
        raise URLNotFoundError(code)

    if encode(url_id) != code:
        raise URLNotFoundError(code)

    original_url = url_cache.get(url_id)

    if original_url is None:
        row = get_by_id(db, url_id)
        if row is None:
            # A miss is never cached: a link created a second after this lookup
            # would stay invisible until the TTL expired.
            raise URLNotFoundError(code)
        original_url = row.original_url
        url_cache.put(url_id, original_url)

    increment_clicks(db, url_id)
    return original_url
