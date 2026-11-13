import os
from datetime import date
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from repositories import auth_store

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "ql_session"
_ATTEMPTS = {}
_LOCK = Lock()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


def require_write_header(request: Request):
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-QuantLab-Request") != "1":
        raise HTTPException(403, "请求校验失败")


def require_user(request: Request):
    token = request.cookies.get(COOKIE)
    user = auth_store.session_user(token) if token and len(token) == 43 else None
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def throttle(request: Request):
    address = request.client.host if request.client else "unknown"
    now = monotonic()
    with _LOCK:
        for key, (deadline, _) in list(_ATTEMPTS.items()):
            if deadline <= now:
                del _ATTEMPTS[key]
        deadline, count = _ATTEMPTS.get(address, (now + 60, 0))
        if count >= 10 or (address not in _ATTEMPTS and len(_ATTEMPTS) >= 4096):
            raise HTTPException(429, "登录尝试过多，请稍后再试")
        _ATTEMPTS[address] = (deadline, count + 1)


@router.post("/login", dependencies=[Depends(require_write_header)])
def login(credentials: Credentials, request: Request, response: Response):
    throttle(request)
    lifetime = 7 * 86400 if credentials.remember else 8 * 3600
    result = auth_store.authenticate(credentials.username.strip(), credentials.password, lifetime)
    if not result:
        raise HTTPException(401, "用户名或密码错误")
    token, user = result
    previous = request.cookies.get(COOKIE)
    if previous and len(previous) == 43:
        auth_store.revoke(previous)
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv("QL_AUTH_SECURE_COOKIE", "1") != "0",
                        samesite="lax", max_age=lifetime if credentials.remember else None)
    response.headers["Cache-Control"] = "no-store"
    return user


@router.get("/me")
def me(response: Response, user=Depends(require_user)):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", dependencies=[Depends(require_write_header)])
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token and len(token) == 43:
        with auth_store.transaction() as cursor:
            auth_store.initialize_audit(cursor)
            digest = auth_store.token_hash(token)
            cursor.execute("SELECT username FROM ql_auth_sessions JOIN ql_auth_users ON ql_auth_users.id=user_id WHERE token_hash=%s", (digest,))
            user = cursor.fetchone()
            cursor.execute("DELETE FROM ql_auth_sessions WHERE token_hash=%s", (digest,))
            if user and cursor.rowcount:
                auth_store.audit(cursor, user["username"], "logout")
    response.delete_cookie(COOKIE)
    return {"ok": True}

def require_admin(user=Depends(require_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "仅管理员可执行此操作")
    return user


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=12, max_length=256)


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=256)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


@router.post("/password", dependencies=[Depends(require_write_header)])
def change_password(body: PasswordChange, response: Response, user=Depends(require_user)):
    with auth_store.transaction() as cursor:
        auth_store.initialize_audit(cursor)
        cursor.execute("SELECT password_hash FROM ql_auth_users WHERE id=%s AND enabled=TRUE FOR UPDATE", (user["id"],))
        row = cursor.fetchone()
        if not row or not auth_store.verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(400, "当前密码错误")
        cursor.execute("UPDATE ql_auth_users SET password_hash=%s WHERE id=%s",
                       (auth_store.password_hash(body.password), user["id"]))
        cursor.execute("DELETE FROM ql_auth_sessions WHERE user_id=%s", (user["id"],))
        auth_store.audit(cursor, user["username"], "change_password")
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/users")
def users(_admin=Depends(require_admin)):
    with auth_store.transaction() as cursor:
        cursor.execute("SELECT id, username, display_name, role, enabled FROM ql_auth_users ORDER BY id")
        return cursor.fetchall()


@router.post("/users", dependencies=[Depends(require_write_header)])
def create_user(body: NewUser, admin=Depends(require_admin)):
    from pymysql.err import IntegrityError

    username, name = body.username.strip(), body.display_name.strip()
    if not username or not name:
        raise HTTPException(422, "用户名和显示名不能为空")
    hashed = auth_store.password_hash(body.password)
    try:
        with auth_store.transaction() as cursor:
            auth_store.initialize_audit(cursor)
            cursor.execute(
                "INSERT INTO ql_auth_users (username, display_name, password_hash, role) VALUES (%s,%s,%s,'researcher')",
                (username, name, hashed),
            )
            auth_store.audit(cursor, admin["username"], "create_user", username)
    except IntegrityError as exc:
        if exc.args[0] == 1062:
            raise HTTPException(409, "用户名已存在") from exc
        raise
    return {"ok": True}


@router.post("/users/{user_id}", dependencies=[Depends(require_write_header)])
def update_user(user_id: int, body: UserUpdate, admin=Depends(require_admin)):
    name = body.display_name.strip() if body.display_name is not None else None
    if name == "":
        raise HTTPException(422, "显示名不能为空")
    if body.enabled is None and body.password is None and name is None:
        raise HTTPException(422, "请选择要更新的内容")
    hashed = auth_store.password_hash(body.password) if body.password else None
    with auth_store.transaction() as cursor:
        auth_store.initialize_audit(cursor)
        cursor.execute("SELECT username, role FROM ql_auth_users WHERE id=%s FOR UPDATE", (user_id,))
        target = cursor.fetchone()
        if not target:
            raise HTTPException(404, "账号不存在")
        if target["role"] != "researcher":
            raise HTTPException(403, "网页管理仅支持研究员账号")
        if name is not None:
            cursor.execute("UPDATE ql_auth_users SET display_name=%s WHERE id=%s", (name, user_id))
            auth_store.audit(cursor, admin["username"], "rename_user", target["username"])
        if body.enabled is not None:
            cursor.execute("UPDATE ql_auth_users SET enabled=%s WHERE id=%s", (body.enabled, user_id))
            auth_store.audit(cursor, admin["username"], "enable_user" if body.enabled else "disable_user", target["username"])
        if hashed:
            cursor.execute("UPDATE ql_auth_users SET password_hash=%s WHERE id=%s", (hashed, user_id))
            auth_store.audit(cursor, admin["username"], "reset_password", target["username"])
        if hashed or body.enabled is False:
            cursor.execute("DELETE FROM ql_auth_sessions WHERE user_id=%s", (user_id,))
    return {"ok": True}


@router.get("/audit")
def audit_log(actor: str = "", action: str = "", start: date | None = None,
              end: date | None = None, offset: int = Query(0, ge=0), _admin=Depends(require_admin)):
    filters, params = [], []
    for value, condition in ((actor, "actor=%s"), (action, "action=%s"), (start, "created_at >= %s"),
                             (end, "created_at < DATE_ADD(%s, INTERVAL 1 DAY)")):
        if value:
            filters.append(condition)
            params.append(value)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    with auth_store.transaction() as cursor:
        auth_store.initialize_audit(cursor)
        cursor.execute("SELECT COUNT(*) AS total FROM ql_auth_audit" + where, params)
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT * FROM ql_auth_audit" + where + " ORDER BY id DESC LIMIT 20 OFFSET %s", [*params, offset])
        return {"total": total, "items": cursor.fetchall()}
