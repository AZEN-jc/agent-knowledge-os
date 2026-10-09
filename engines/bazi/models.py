"""八字引擎的领域数据模型。

本模块只定义输入输出契约，不实现历法算法。这样在接入第三方引擎时，
排盘结果仍然必须经过统一的数据边界和校验。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BirthInput:
    """出生信息；时间按出生地当地民用时间解释。"""

    year: int
    month: int
    day: int
    hour: int
    minute: int = 0
    longitude: float | None = None
    latitude: float | None = None
    timezone: str = "Asia/Shanghai"
    gender: str | None = None

    def __post_init__(self) -> None:
        try:
            datetime(self.year, self.month, self.day, self.hour, self.minute)
        except ValueError as exc:
            raise ValueError(f"出生日期时间无效：{exc}") from exc
        if not -180 <= (self.longitude if self.longitude is not None else 0) <= 180:
            raise ValueError("longitude 必须在 -180 到 180 之间。")
        if not -90 <= (self.latitude if self.latitude is not None else 0) <= 90:
            raise ValueError("latitude 必须在 -90 到 90 之间。")
        if self.gender not in (None, "男", "女", "male", "female"):
            raise ValueError("gender 只能是 男、女、male、female 或 None。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def instant(self) -> datetime:
        """出生时刻的绝对时间（带出生地时区）。

        节气是天文事件，只能按绝对时刻比较；民用时与真太阳时的差别属于
        另一层，不参与年月分界判定。注意 ``Asia/Shanghai`` 在 1986-1991 年
        夏季为 UTC+9，这里由 tzdata 正确还原，不要手工加偏移。
        """
        return datetime(
            self.year, self.month, self.day, self.hour, self.minute,
            tzinfo=ZoneInfo(self.timezone),
        )


@dataclass(frozen=True)
class Pillar:
    """一柱干支及其可选派生字段。"""

    name: str
    heavenly_stem: str
    earthly_branch: str
    hidden_stems: tuple[str, ...] = ()
    ten_god: str | None = None
    na_yin: str | None = None


@dataclass(frozen=True)
class Chart:
    """统一命盘输出；provider 必须填写实际算法来源。"""

    birth: BirthInput
    pillars: tuple[Pillar, ...]
    day_master: str | None = None
    elements: dict[str, Any] = field(default_factory=dict)
    dayun: tuple[dict[str, Any], ...] = ()
    relations: tuple[dict[str, Any], ...] = ()
    provider: str = ""
    algorithm_version: str = ""

    def __post_init__(self) -> None:
        if len(self.pillars) != 4:
            raise ValueError("Chart 必须包含年、月、日、时四柱。")
        if not self.provider.strip():
            raise ValueError("Chart 必须标明 provider。")
        if not self.algorithm_version.strip():
            raise ValueError("Chart 必须标明 algorithm_version。")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["birth"] = self.birth.to_dict()
        result["pillars"] = [asdict(pillar) for pillar in self.pillars]
        return result
