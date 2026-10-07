"""熬锅规则：出胶门槛（最近峰值 ≥ 90℃）与整坊鼓风分钟配额。"""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import Session, select

from app.models import BlowerQuota, Kettle

MIN_PEAK = 90.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Kettle.STATUS_DRAWN:
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")


def consume_blower_minute(session: Session, workshop_id: int) -> None:
    """登记峰值时在同一事务内扣减 1 分钟。

    只发一条条件 UPDATE 并持行锁至提交：两名工抢交时，后到事务等锁释放后，
    PostgreSQL（READ COMMITTED）按新行版本重判 remaining_minutes >= 1，
    剩 0 即命中 0 行、抛 RuleError，峰值行因此不得入库。分钟不掺进出胶
    门槛，改锅态也不走这里。
    """
    result = session.execute(
        update(BlowerQuota)
        .where(
            BlowerQuota.workshop_id == workshop_id,
            BlowerQuota.remaining_minutes >= 1,
        )
        .values(
            remaining_minutes=BlowerQuota.remaining_minutes - 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 1:
        return
    quota = session.exec(
        select(BlowerQuota).where(BlowerQuota.workshop_id == workshop_id)
    ).first()
    if quota is None:
        raise RuleError("该坊尚无鼓风配额，请联系管理员")
    raise RuleError("鼓风剩余分钟不足 1 分钟，无法登记峰值")


def add_blower_minutes(session: Session, workshop_id: int, minutes: int) -> BlowerQuota:
    result = session.execute(
        update(BlowerQuota)
        .where(BlowerQuota.workshop_id == workshop_id)
        .values(
            remaining_minutes=BlowerQuota.remaining_minutes + minutes,
            updated_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount != 1:
        raise RuleError("该坊尚无鼓风配额")
    return session.exec(
        select(BlowerQuota).where(BlowerQuota.workshop_id == workshop_id)
    ).first()
