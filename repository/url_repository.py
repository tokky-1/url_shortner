from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models.url import URL

def create(db: Session, link: URL) -> URL:
    try:
        db.add(link)
        db.commit()
        db.refresh(link)
        return link
    except Exception:
        db.rollback()
        raise

def get_by_id(db: Session, url_id: int) -> URL | None:
    return db.query(URL).filter(URL.id == url_id).first()

def increment_clicks(db: Session, url_id: int) -> None:
    db.query(URL).filter(URL.id == url_id).update(
        {URL.clicks: URL.clicks + 1},
        synchronize_session=False,
    )
    db.commit()
