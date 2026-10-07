from sqlmodel import select

from app.db import get_session
from app.models import BlowerQuota, CookLog, Kettle, User, Workshop
from app.security import hash_password


def _ensure_user(session, username, role):
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        session.add(User(username=username, password_hash=hash_password("123456"), role=role))
    else:
        user.password_hash = hash_password("123456")
        user.role = role


def _ensure_workshop(session, name, alley, layout):
    shop = session.exec(select(Workshop).where(Workshop.name == name)).first()
    if shop is None:
        shop = Workshop(name=name, alley=alley)
        session.add(shop)
        session.flush()
        for code, status, bench, peak in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
        session.flush()
    return shop


def _ensure_quota(session, workshop_id, minutes):
    """只补缺额行，不重置已存在的配额（补过的分钟与已耗分钟须保留）。"""
    quota = session.exec(select(BlowerQuota).where(BlowerQuota.workshop_id == workshop_id)).first()
    if quota is None:
        session.add(BlowerQuota(workshop_id=workshop_id, remaining_minutes=minutes))


def seed_demo() -> None:
    with get_session() as session:
        _ensure_user(session, "admin", "admin")
        _ensure_user(session, "worker", "worker")

        _ensure_workshop(
            session,
            "骨巷熬胶坊",
            "西市骨巷",
            [
                ("锅-1", Kettle.STATUS_BOILING, 0, 96.0),
                ("锅-2", Kettle.STATUS_COLD, 1, None),
                ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0),
                ("锅-4", Kettle.STATUS_BOILING, 3, 82.0),
                ("锅-5", Kettle.STATUS_COLD, 4, None),
                ("锅-6", Kettle.STATUS_DRAWN, 5, 94.0),
            ],
        )
        _ensure_workshop(
            session,
            "皮巷熬胶坊",
            "东市皮巷",
            [
                ("皮锅-1", Kettle.STATUS_COLD, 0, None),
                ("皮锅-2", Kettle.STATUS_BOILING, 1, 91.0),
            ],
        )
        # 种子：每个坊整坊鼓风剩余 1 分钟（配额按坊共用一行）。
        for shop in session.exec(select(Workshop)).all():
            _ensure_quota(session, shop.id, 1)
        session.commit()
