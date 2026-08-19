"""RBAC как в Koseven: users, roles, roles_users, user_tokens."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from specgraph.db import SessionLocal, get_db
from specgraph.models import Role, User, UserToken

COOKIE = "specgraph_token"
TOKEN_TTL = 14 * 24 * 3600

KOSEVEN_ROLES = (
    ("login", "Login privileges, granted after account confirmation"),
    ("admin", "Administrative user, has access to everything."),
    ("pipeline", "Может запускать любые пайплайны"),
)


def hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        algo, salt, hx = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 120_000)
    return hmac.compare_digest(dk.hex(), hx)


def role_names(user: User) -> set[str]:
    return {r.name for r in (user.roles or [])}


def has_role(user: User | None, name: str) -> bool:
    return bool(user and name in role_names(user))


def is_admin(user: User | None) -> bool:
    return has_role(user, "admin")


def can_run_pipeline(user: User | None, pipeline: str) -> bool:
    """Гость — да. Залогинен — admin / pipeline / роль с именем пайплайна."""
    if user is None:
        return True
    names = role_names(user)
    return bool(names & {"admin", "pipeline", pipeline})


def user_public(user: User) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email, "roles": sorted(role_names(user))}


def issue_token(db: Session, user: User, user_agent: str = "") -> UserToken:
    now = int(time.time())
    tok = UserToken(
        user_id=user.id,
        user_agent=(user_agent or "")[:40],
        token=secrets.token_hex(20),
        created=now,
        expires=now + TOKEN_TTL,
    )
    db.add(tok)
    user.logins = (user.logins or 0) + 1
    user.last_login = now
    db.commit()
    db.refresh(tok)
    return tok


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.query(UserToken).filter(UserToken.token == token).first()
    if not row or row.expires < int(time.time()):
        return None
    return db.get(User, row.user_id)


def optional_user(
    db: Session = Depends(get_db),
    specgraph_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    raw = specgraph_token
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    return user_from_token(db, raw)


def require_admin(user: User | None = Depends(optional_user)) -> User:
    if not is_admin(user):
        raise HTTPException(403, "нужна роль admin")
    return user


def ensure_roles(db: Session) -> None:
    have = {r.name for r in db.query(Role).all()}
    for name, desc in KOSEVEN_ROLES:
        if name not in have:
            db.add(Role(name=name, description=desc))
            have.add(name)
    try:
        from specgraph.pipelines.graphs import _catalog

        for pname in _catalog():
            if pname.startswith("_") or pname in have:
                continue
            db.add(Role(name=pname, description=f"Запуск пайплайна {pname}"))
            have.add(pname)
    except Exception:  # noqa: BLE001
        pass
    db.commit()


def get_or_create_role(db: Session, name: str, description: str = "") -> Role:
    r = db.query(Role).filter(Role.name == name).first()
    if r:
        return r
    r = Role(name=name, description=description)
    db.add(r)
    db.flush()
    return r


def attach_roles(db: Session, user: User, names: list[str]) -> None:
    have = {r.name for r in user.roles}
    for n in names:
        if n in have:
            continue
        user.roles.append(get_or_create_role(db, n))
    db.commit()


def seed_admin() -> None:
    from specgraph.config import settings

    user = settings.admin_username.strip()
    pwd = settings.admin_password
    if not user or not pwd:
        return
    db = SessionLocal()
    try:
        ensure_roles(db)
        u = db.query(User).filter(User.username == user).first()
        if u:
            return
        email = settings.admin_email.strip() or f"{user}@local"
        u = User(username=user[:32], email=email[:254], password=hash_password(pwd), logins=0)
        db.add(u)
        db.flush()
        attach_roles(db, u, ["login", "admin", "pipeline"])
    finally:
        db.close()
