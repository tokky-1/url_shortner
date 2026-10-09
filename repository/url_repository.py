from sqlalchemy.orm import Session
from models.url import URL

def create(db: Session, link: str) -> URL:
    try:
        url = URL(original_url=link)
        db.add(url)
        db.commit()
        db.refresh(url)
        return url
    except Exception:
        db.rollback()
        raise

def get_by_id(db: Session, url_id: int) -> URL | None:
    return db.query(URL).filter(URL.id == url_id).first()

def increment_clicks(db: Session, url_id: int) -> None:
    try:
        db.query(URL).filter(URL.id == url_id).update(
            {URL.clicks: URL.clicks + 1},
            synchronize_session="fetch",
        )
        db.commit()
    except Exception:
            db.rollback()
            raise
