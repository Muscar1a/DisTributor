import hashlib

from sqlalchemy.orm import Session

from src.gateway.app.db.crud import get_api_key_by_hash
from src.gateway.app.db.session import SessionLocal


def verify_db_api_key(raw_key: str, db: Session | None = None):
    if not raw_key:
        return None
    owns_session = db is None
    session = db or SessionLocal()
    try:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        return get_api_key_by_hash(session, key_hash)
    finally:
        if owns_session:
            session.close()
