from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    RuleError,
    assert_can_set_status,
    consume_blower_minute,
    latest_peak,
    top_up_blower_minutes,
)
from app.models import BlowerQuota, CookLog, Kettle, User, Workshop
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle).where(Kettle.id == kettle_id).options(selectinload(Kettle.cooks))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
    }


def quota_json(quota: BlowerQuota, workshop_name: str = "") -> dict:
    return {
        "id": quota.id,
        "workshopId": quota.workshop_id,
        "workshop": workshop_name,
        "remainingMinutes": quota.remaining_minutes,
        "updatedAt": quota.updated_at.isoformat() if quota.updated_at else None,
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        quota = session.exec(
            select(BlowerQuota).where(BlowerQuota.workshop_id == shop.id)
        ).first()
        return JSONResponse(
            {
                "workshop": shop.name,
                "alley": shop.alley,
                "kettles": [kettle_json(k) for k in loaded],
                "blower": quota_json(quota, shop.name) if quota else None,
            }
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            consume_blower_minute(session, kettle.workshop_id)
        except RuleError as exc:
            session.rollback()
            return JSONResponse({"detail": str(exc)}, status_code=400)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def blower_quotas(request: Request):
    """配额专页数据：坊、剩余分钟、更新时刻。登录即可读（操作工只读）。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        quotas = session.exec(select(BlowerQuota).order_by(BlowerQuota.id)).all()
        shops = {s.id: s.name for s in session.exec(select(Workshop)).all()}
        return JSONResponse(
            {"quotas": [quota_json(q, shops.get(q.workshop_id, "")) for q in quotas]}
        )


async def replenish_quota(request: Request):
    """管理员补分钟：把剩余分钟补回去，须为正整数。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if user.role != "admin":
        return JSONResponse({"detail": "仅管理员可补分钟"}, status_code=403)
    quota_id = int(request.path_params["quota_id"])
    body = await request.json()
    minutes = body.get("minutes")
    if isinstance(minutes, str) and minutes.strip().isdigit():
        minutes = int(minutes.strip())
    with get_session() as session:
        try:
            quota = top_up_blower_minutes(session, quota_id, minutes)
        except RuleError as exc:
            session.rollback()
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except KeyError:
            session.rollback()
            return JSONResponse({"detail": "配额不存在"}, status_code=404)
        session.commit()
        session.refresh(quota)
        shop = session.get(Workshop, quota.workshop_id)
        return JSONResponse(quota_json(quota, shop.name if shop else ""))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/blower/quotas", blower_quotas),
        Route("/api/blower/quotas/{quota_id:int}/replenish", replenish_quota, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
