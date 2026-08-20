from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from specgraph.auth import attach_roles, can_run_pipeline, ensure_roles, hash_password, is_admin, verify_password
from specgraph.db import Base, wipe_db
from specgraph.models import Document, Role, User


def _mem(monkeypatch, tmp_path):
    from specgraph import db as dbmod

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    return Session()


def test_koseven_roles_and_password(tmp_path, monkeypatch):
    db = _mem(monkeypatch, tmp_path)
    ensure_roles(db)
    names = {r.name for r in db.query(Role).all()}
    assert {"login", "admin", "pipeline"} <= names
    assert verify_password("x", hash_password("x"))
    assert not verify_password("y", hash_password("x"))


def test_guest_can_pipeline_logged_needs_role(tmp_path, monkeypatch):
    db = _mem(monkeypatch, tmp_path)
    ensure_roles(db)
    assert can_run_pipeline(None, "review-correctness") is True
    u = User(username="u", email="u@l", password=hash_password("p"), logins=0)
    db.add(u)
    db.flush()
    attach_roles(db, u, ["login"])
    db.refresh(u)
    assert can_run_pipeline(u, "review-correctness") is False
    attach_roles(db, u, ["pipeline"])
    db.refresh(u)
    assert can_run_pipeline(u, "review-correctness") is True
    assert not is_admin(u)


def test_wipe_keeps_users(tmp_path, monkeypatch):
    db = _mem(monkeypatch, tmp_path)
    ensure_roles(db)
    u = User(username="a", email="a@l", password=hash_password("p"), logins=0)
    db.add(u)
    db.add(Document(filename="x.docx", kind="docx", storage_path="x", status="parsed"))
    db.commit()
    wipe_db()
    db2 = type(db)()
    # new session from same Session factory
    from specgraph.db import SessionLocal

    db2 = SessionLocal()
    assert db2.query(User).filter_by(username="a").one()
    assert db2.query(Document).count() == 0
