import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import create_engine, String, Integer, Index
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column

# Globals
_engine = None
_SessionLocal = None
_db_path: Optional[str] = None


Base = declarative_base()


def _current_ts() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat(sep=' ')


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        Index("idx_people_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    surname: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    photo_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    data_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    report_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=_current_ts)
    updated_at: Mapped[str] = mapped_column(String, default=_current_ts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "surname": self.surname,
            "phone": self.phone,
            "photo_path": self.photo_path,
            "status": self.status,
            "summary": self.summary,
            "data_json": self.data_json,
            "report_text": self.report_text,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _make_sqlite_url(db_path: str) -> str:
    # Ensure absolute path and normalize for SQLAlchemy URL
    abs_path = os.path.abspath(db_path).replace("\\", "/")
    return f"sqlite:///{abs_path}"


def init_db(db_path: str):
    global _engine, _SessionLocal, _db_path
    _db_path = db_path
    dirpath = os.path.dirname(db_path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    # Use SQLAlchemy engine
    url = _make_sqlite_url(db_path)
    _engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    # Create tables
    Base.metadata.create_all(_engine)


def _get_session():
    if _SessionLocal is None:
        raise RuntimeError("DB is not initialized. Call init_db(db_path) first.")
    return _SessionLocal()


def create_person(first_name: str = "", last_name: str = "", surname: str = "", phone: str = "", photo_path: Optional[str] = None) -> int:
    with _get_session() as session:
        person = Person(
            first_name=first_name or "",
            last_name=last_name or "",
            surname=surname or "",
            phone=phone or "",
            photo_path=photo_path,
            status="active",
            created_at=_current_ts(),
            updated_at=_current_ts(),
        )
        session.add(person)
        session.commit()
        session.refresh(person)
        return int(person.id)


def list_people(include_archived: bool = False) -> List[Dict[str, Any]]:
    with _get_session() as session:
        q = session.query(Person)
        if not include_archived:
            q = q.filter(Person.status == "active")
        rows = q.order_by(Person.updated_at.desc(), Person.id.desc()).all()
        return [p.to_dict() for p in rows]


def get_person(person_id: int) -> Optional[Dict[str, Any]]:
    with _get_session() as session:
        p = session.get(Person, person_id)
        return p.to_dict() if p else None


def update_person(person_id: int, **fields):
    if not fields:
        return
    allowed = {"first_name", "last_name", "surname", "phone", "photo_path", "status", "summary", "data_json", "report_text"}
    update_data = {k: v for k, v in fields.items() if k in allowed}
    if not update_data:
        return
    update_data["updated_at"] = _current_ts()
    with _get_session() as session:
        session.query(Person).filter(Person.id == person_id).update(update_data)
        session.commit()


def archive_person(person_id: int):
    update_person(person_id, status='archived')


def delete_person(person_id: int):
    with _get_session() as session:
        p = session.get(Person, person_id)
        if p is not None:
            session.delete(p)
            session.commit()