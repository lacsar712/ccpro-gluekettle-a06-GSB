from sqlmodel import select

from app.db import get_session
from app.models import BlowerQuota, CookLog, Kettle, User, Workshop
from app.security import hash_password

SEED_BLOWER_MINUTES = 1


def ensure_blower_quotas(session) -> None:
    """给还没有配额行的坊补建，剩余分钟写成 1；已有行不动。"""
    shops = session.exec(select(Workshop)).all()
    have = set(session.exec(select(BlowerQuota.workshop_id)).all())
    for shop in shops:
        if shop.id not in have:
            session.add(BlowerQuota(workshop_id=shop.id, remaining_minutes=SEED_BLOWER_MINUTES))


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"
        if session.exec(select(Workshop)).first():
            ensure_blower_quotas(session)
            session.commit()
            return
        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        layout = [
            ("锅-1", Kettle.STATUS_BOILING, 0, 96.0),
            ("锅-2", Kettle.STATUS_COLD, 1, None),
            ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0),
            ("锅-4", Kettle.STATUS_BOILING, 3, 82.0),
            ("锅-5", Kettle.STATUS_COLD, 4, None),
            ("锅-6", Kettle.STATUS_DRAWN, 5, 94.0),
        ]
        for code, status, bench, peak in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
        session.add(BlowerQuota(workshop_id=shop.id, remaining_minutes=SEED_BLOWER_MINUTES))
        session.commit()
