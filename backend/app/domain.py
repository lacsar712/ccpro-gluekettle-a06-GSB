"""熬锅出胶门槛：最近一次煮胶峰值温度须 ≥ 90℃。

鼓风配额门槛：登记一次峰值须在同一事务内原子扣减 1 分钟；
剩余不足 1 分钟则整笔挡下，峰值不得入库。改锅态不扣分钟，
分钟不掺进已出胶门槛。
"""

from sqlalchemy import update
from sqlmodel import Session

from app.models import BlowerQuota, Kettle, utcnow

MIN_PEAK = 90.0
COOK_MINUTE_COST = 1


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
    """同一事务内原子扣 1 分钟鼓风配额。

    单条 UPDATE ... WHERE remaining_minutes >= 1：行锁保证并发下
    后到者重估条件落空（rowcount 为 0），绝不扣成负数。
    调用方须在同一事务里再落 CookLog，扣减与入库同生同死。
    """
    result = session.execute(
        update(BlowerQuota)
        .where(BlowerQuota.workshop_id == workshop_id)
        .where(BlowerQuota.remaining_minutes >= COOK_MINUTE_COST)
        .values(
            remaining_minutes=BlowerQuota.remaining_minutes - COOK_MINUTE_COST,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise RuleError("鼓风剩余分钟不足，不能登记峰值")


def top_up_blower_minutes(session: Session, quota_id: int, minutes: int) -> BlowerQuota:
    """管理员补分钟：原子加回，分钟须为正整数。"""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        raise RuleError("补分钟必须是正整数")
    result = session.execute(
        update(BlowerQuota)
        .where(BlowerQuota.id == quota_id)
        .values(
            remaining_minutes=BlowerQuota.remaining_minutes + minutes,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise KeyError(quota_id)
    return session.get(BlowerQuota, quota_id)
