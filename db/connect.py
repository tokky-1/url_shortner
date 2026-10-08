from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from core.config import get_settings

Base = declarative_base()

@lru_cache
def get_engine():
    settings = get_settings()
    return create_engine(
        settings.DB_URL,
        connect_args={"connect_timeout": 5},
        pool_pre_ping=True,
    )

@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)

def get_db():
    db: Session = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
