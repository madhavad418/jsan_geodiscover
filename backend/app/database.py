from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings

settings = get_settings()
url = settings.sqlalchemy_url
connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine_kwargs = {}
if not url.startswith("sqlite"):
    # A hosted database drops idle connections, so verify one before handing it out.
    engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 300}
engine = create_engine(url, connect_args=connect_args, future=True, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
