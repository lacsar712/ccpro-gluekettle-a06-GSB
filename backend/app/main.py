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
    add_blower_minutes,
    assert_can_set_status,
    consume_blower_minute,
    latest_peak,
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


def require_admin(user: User | None):
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if user.role != "admin":
        return JSONResponse({"detail": "需要管理员权限"}, status_code=403)
    return None


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle).where(Kettle.id == kettle_id).options(selectinload(Kettle.cooks))
    ).first()


def load_quota(session, workshop_id: int) -> BlowerQuota | None:
    return session.exec(
        select(BlowerQuota).where(BlowerQuota.workshop_id == workshop_id)
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "workshopId": kettle.workshop_id,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
    }


def quota_json(quota: BlowerQuota, workshop: Workshop) -> dict:
    return {
        "workshopId": workshop.id,
        "workshopName": workshop.name,
        "alley": workshop.alley,
        "remainingMinutes": quota.remaining_minutes,
        "updatedAt": quota.updated_at.isoformat(),
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


async def workshops(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shops = session.exec(select(Workshop).order_by(Workshop.id)).all()
        return JSONResponse(
            [{"id": s.id, "name": s.name, "alley": s.alley} for s in shops]
        )


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop_id = request.query_params.get("workshop_id")
        if shop_id:
            try:
                shop_id = int(shop_id)
            except ValueError:
                return JSONResponse({"detail": "坊编号必须是整数"}, status_code=400)
            shop = session.exec(select(Workshop).where(Workshop.id == shop_id)).first()
        else:
            shop = session.exec(select(Workshop).order_by(Workshop.id)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks))
        ).all()
        quota = load_quota(session, shop.id)
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {
                "workshopId": shop.id,
                "workshop": shop.name,
                "alley": shop.alley,
                "remainingMinutes": quota.remaining_minutes if quota else None,
                "kettles": [kettle_json(k) for k in loaded],
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
            # 先扣分钟再插峰值，同一事务提交：扣不中则整体回滚，峰值不得入库。
            consume_blower_minute(session, kettle.workshop_id)
            session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
            session.commit()
        except RuleError as exc:
            session.rollback()
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle = load_kettle(session, kettle_id)
        quota = load_quota(session, kettle.workshop_id)
        payload = kettle_json(kettle)
        payload["remainingMinutes"] = quota.remaining_minutes if quota else None
        return JSONResponse(payload)


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
            # 改锅态不扣鼓风分钟；出胶门槛照旧只看最近峰值，分钟不掺进来。
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_quotas(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        stmt = (
            select(BlowerQuota, Workshop)
            .join(Workshop, BlowerQuota.workshop_id == Workshop.id)
            .order_by(Workshop.id)
        )
        shop_id = request.query_params.get("workshop_id")
        if shop_id:
            try:
                shop_id = int(shop_id)
            except ValueError:
                return JSONResponse({"detail": "坊编号必须是整数"}, status_code=400)
            stmt = stmt.where(BlowerQuota.workshop_id == shop_id)
        rows = session.execute(stmt).all()
        return JSONResponse([quota_json(q, s) for q, s in rows])


async def topup_quota(request: Request):
    user = await current_user(request)
    denied = require_admin(user)
    if denied is not None:
        return denied
    workshop_id = int(request.path_params["workshop_id"])
    body = await request.json()
    minutes = body.get("minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        return JSONResponse({"detail": "补分钟数必须是非负整数"}, status_code=400)
    if minutes < 1:
        return JSONResponse({"detail": "补分钟数须为大于 0 的整数"}, status_code=400)
    with get_session() as session:
        shop = session.exec(select(Workshop).where(Workshop.id == workshop_id)).first()
        if shop is None:
            return JSONResponse({"detail": "坊不存在"}, status_code=404)
        try:
            quota = add_blower_minutes(session, workshop_id, minutes)
            session.commit()
        except RuleError as exc:
            session.rollback()
            return JSONResponse({"detail": str(exc)}, status_code=404)
        session.refresh(quota)
        return JSONResponse(quota_json(quota, shop))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/workshops", workshops),
        Route("/api/board", board),
        Route("/api/quotas", list_quotas),
        Route("/api/quotas/{workshop_id:int}/topup", topup_quota, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
