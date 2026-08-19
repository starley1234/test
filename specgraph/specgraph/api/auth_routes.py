from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from specgraph.auth import (
    COOKIE,
    TOKEN_TTL,
    attach_roles,
    ensure_roles,
    hash_password,
    issue_token,
    optional_user,
    require_admin,
    user_public,
    verify_password,
)
from specgraph.db import get_db
from specgraph.models import Role, RoleUser, User

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    email: str | None = None


class RolesIn(BaseModel):
    roles: list[str]


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=TOKEN_TTL, path="/")


@router.post("/register")
def register(body: AuthIn, response: Response, db: Session = Depends(get_db)):
    ensure_roles(db)
    name = body.username.strip()
    if db.query(User).filter((User.username == name) | (User.email == (body.email or name))).first():
        raise HTTPException(400, "пользователь уже есть")
    email = (body.email or f"{name}@local").strip()[:254]
    u = User(username=name, email=email, password=hash_password(body.password), logins=0)
    db.add(u)
    db.flush()
    attach_roles(db, u, ["login", "pipeline"])
    tok = issue_token(db, u)
    _set_cookie(response, tok.token)
    return {"user": user_public(u), "token": tok.token}


@router.post("/login")
def login(body: AuthIn, response: Response, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.username.strip()).first()
    if not u or not verify_password(body.password, u.password):
        raise HTTPException(401, "неверный логин или пароль")
    tok = issue_token(db, u)
    _set_cookie(response, tok.token)
    return {"user": user_public(u), "token": tok.token}


@router.post("/logout")
def logout(response: Response, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User | None = Depends(optional_user)):
    if not user:
        return {"user": None, "guest": True}
    return {"user": user_public(user), "guest": False}


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [user_public(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users/{user_id}/roles")
def set_roles(user_id: int, body: RolesIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404)
    ensure_roles(db)
    db.query(RoleUser).filter(RoleUser.user_id == u.id).delete()
    db.commit()
    db.refresh(u)
    attach_roles(db, u, body.roles)
    db.refresh(u)
    return user_public(u)


@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name, "description": r.description} for r in db.query(Role).order_by(Role.id).all()]
