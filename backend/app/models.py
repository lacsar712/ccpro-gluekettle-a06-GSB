from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import CheckConstraint
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")
    quota: Optional["BlowerQuota"] = Relationship(back_populates="workshop", sa_relationship_kwargs={"uselist": False})


class BlowerQuota(SQLModel, table=True):
    """整坊鼓风配额：行级条件扣减，保证抢交时只许一条峰值入库。"""

    __tablename__ = "blowerquota"
    __table_args__ = (CheckConstraint("remaining_minutes >= 0", name="blowerquota_minutes_nonneg"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id", unique=True, index=True)
    remaining_minutes: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utcnow)
    workshop: Optional[Workshop] = Relationship(back_populates="quota")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")
