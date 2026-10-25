"""基于 sxtwl 的四柱 provider。

边界说明：sxtwl 负责天文历法和干支计算；本适配器只负责把结果转成项目
模型。大运、格局、用神和流派规则不在这里实现，避免把历法结果与命理解释混为一谈。

年柱和月柱不取 sxtwl 的 ``getYearGZ()`` / ``getMonthGZ()`` —— 那两个接口只按
**日期**分界（立春当天 00:00 就换年），节气日当天、节气时刻之前出生的人会拿到
错的年月柱。这里改由 :mod:`engines.bazi.jieqi` 按节气精确时刻判定。

晚子时（23:00-24:00）的处理是流派分歧点，这里显式化为 ``late_zi_policy``：

- ``no_roll``（默认）：沿用 sxtwl 的口径 —— 日柱仍属当日，时柱天干按**次日**日干推。
  实测 ``getHourGZ(23)`` 在 1990-06-15（辛亥日）返回庚子，而庚子正是次日壬子日的子时。
- ``roll``：23:00 起日柱即进次日，时柱为次日子时（子时换日）。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import sxtwl

from engines.bazi.auxiliary import auxiliary_of
from engines.bazi.jieqi import month_pillar, year_pillar
from engines.bazi.models import BirthInput, Chart, Pillar
from engines.bazi.ten_gods import BRANCHES, ELEMENTS, STEMS, element_census, ten_god

HIDDEN_STEMS: dict[str, tuple[str, ...]] = {
    "子": ("癸",),
    "丑": ("己", "癸", "辛"),
    "寅": ("甲", "丙", "戊"),
    "卯": ("乙",),
    "辰": ("戊", "乙", "癸"),
    "巳": ("丙", "戊", "庚"),
    "午": ("丁", "己"),
    "未": ("己", "丁", "乙"),
    "申": ("庚", "壬", "戊"),
    "酉": ("辛",),
    "戌": ("戊", "辛", "丁"),
    "亥": ("壬", "甲"),
}

NA_YIN = (
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火", "涧下水", "城头土",
    "白蜡金", "杨柳木", "泉中水", "屋上土", "霹雳火", "松柏木", "长流水", "砂中金",
    "山下火", "平地木", "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
)

BRANCH_RELATIONS = {
    "六合": {frozenset(pair) for pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")},
    "六冲": {frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")},
    "六害": {frozenset(pair) for pair in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")},
    "相破": {frozenset(pair) for pair in ("子酉", "寅亥", "卯午", "辰丑", "巳申", "未戌")},
}
SELF_PUNISHMENT = {"辰", "午", "酉", "亥"}
MUTUAL_PUNISHMENT = {frozenset(pair) for pair in ("丑戌未", "寅巳申")}

LATE_ZI_POLICIES = ("no_roll", "roll")
DEFAULT_LATE_ZI_POLICY = "no_roll"


class _SxtwlGanZhi(Protocol):
    """sxtwl 的干支对象。

    sxtwl 是 C 扩展，没有类型存根，mypy 只能看到 ``object``。这里用 Protocol
    把本文件对它的**全部依赖**写在明处：两个整数下标。不用 ``cast`` ——
    cast 同样能消错，但它把「我们假定它有这两个属性」这件事藏进一行调用，
    下一个人改这里的推导时就看不见这个约定了。
    """

    tg: int
    dz: int


def _gz_text(gz: _SxtwlGanZhi) -> tuple[str, str]:
    stem_index = int(gz.tg)
    branch_index = int(gz.dz)
    return STEMS[stem_index], BRANCHES[branch_index]


def _na_yin(stem: str, branch: str) -> str:
    """按六十甲子序号返回纳音；甲子起点为海中金。"""
    stem_index = STEMS.index(stem)
    branch_index = BRANCHES.index(branch)
    cycle_index = next(
        index for index in range(60)
        if index % 10 == stem_index and index % 12 == branch_index
    )
    return NA_YIN[cycle_index // 2]


def _relations(branches: tuple[str, ...]) -> tuple[dict[str, object], ...]:
    """返回四支的结构关系事实，不对关系做吉凶判断。"""
    result: list[dict[str, object]] = []
    names = ("year", "month", "day", "hour")
    for left in range(len(branches)):
        for right in range(left + 1, len(branches)):
            pair = frozenset((branches[left], branches[right]))
            for relation, pairs in BRANCH_RELATIONS.items():
                if pair in pairs:
                    result.append({
                        "type": relation,
                        "branches": [branches[left], branches[right]],
                        "pillars": [names[left], names[right]],
                    })
    for index, branch in enumerate(branches):
        if branch in SELF_PUNISHMENT and branches.count(branch) >= 2:
            result.append({"type": "自刑", "branches": [branch], "pillars": [names[index]]})
    for relation_branches in MUTUAL_PUNISHMENT:
        if relation_branches.issubset(branches):
            result.append({
                "type": "三刑",
                "branches": sorted(relation_branches),
                "pillars": [names[index] for index, branch in enumerate(branches) if branch in relation_branches],
            })
    return tuple(result)


def _equation_of_time_minutes(day_of_year: int) -> float:
    """用 NOAA 常用近似式计算均时差，误差用于校时而非天文科研。"""
    angle = math.radians((360 / 365) * (day_of_year - 81))
    return 9.87 * math.sin(2 * angle) - 7.53 * math.cos(angle) - 1.5 * math.sin(angle)


def _solar_time_datetime(birth: BirthInput) -> datetime:
    """把当地民用时间转换为当地真太阳时的近似 datetime。"""
    if birth.longitude is None:
        raise ValueError("开启真太阳时必须提供 longitude。")
    local = datetime(
        birth.year, birth.month, birth.day, birth.hour, birth.minute,
        tzinfo=ZoneInfo(birth.timezone),
    )
    # utcoffset() 的签名是 timedelta | None：理论上 tzinfo 存在也可能给不出偏移。
    # 上面 ZoneInfo(...) 已构造成功，正常路径到不了 None，但不能因此
    # assert 了事 —— 真到了 None，这里必须给出一个能读懂的错误，而不是
    # AttributeError: 'NoneType' object has no attribute 'total_seconds'。
    offset = local.utcoffset()
    if offset is None:
        raise ValueError(f"时区 {birth.timezone!r} 无法给出 UTC 偏移。")
    standard_meridian = offset.total_seconds() / 3600 * 15
    longitude_minutes = (birth.longitude - standard_meridian) * 4
    equation_minutes = _equation_of_time_minutes(local.timetuple().tm_yday)
    return local + timedelta(minutes=longitude_minutes + equation_minutes)


def _birth_instant(birth: BirthInput) -> datetime:
    """出生时刻的绝对时间；见 :meth:`BirthInput.instant`。"""
    return birth.instant()


class SxtwlBaziProvider:
    """sxtwl 2.x 的四柱适配器。"""

    name = "sxtwl"
    algorithm_version = "sxtwl-2.0.7-bazi-v2"
    supports_true_solar_time = True
    supports_dayun = False
    supports_relations = True

    def __init__(
        self,
        *,
        use_true_solar_time: bool = False,
        late_zi_policy: str = DEFAULT_LATE_ZI_POLICY,
    ) -> None:
        if late_zi_policy not in LATE_ZI_POLICIES:
            raise ValueError(f"late_zi_policy 只能是 {LATE_ZI_POLICIES} 之一。")
        self.use_true_solar_time = use_true_solar_time
        self.late_zi_policy = late_zi_policy
        # 非默认口径必须体现在 provenance 里，否则同版本号会掩盖不同结果。
        # 真太阳时是 Phase 5.2 补的第二条：它同样改变时柱（西端地区可跨两个
        # 时辰），漏记的后果与晚子时漏记相同 —— 两张不同的命盘共用一个版本号，
        # 且错得看不出来。两个口径叠加时后缀累加（+roll+tst），不互相覆盖。
        suffixes = []
        if late_zi_policy != DEFAULT_LATE_ZI_POLICY:
            suffixes.append(late_zi_policy)
        if use_true_solar_time:
            suffixes.append("tst")
        if suffixes:
            self.algorithm_version = f"{type(self).algorithm_version}+{'+'.join(suffixes)}"

    def _day_source(self, calculation_time: datetime) -> tuple[date, int]:
        """返回日柱所属日期与取时柱用的时辰序号。

        ``roll`` 口径下 23:00 起日柱进次日，时柱即次日子时的第 0 时辰。
        """
        if self.late_zi_policy == "roll" and calculation_time.hour == 23:
            return calculation_time.date() + timedelta(days=1), 0
        return calculation_time.date(), calculation_time.hour

    def calculate(self, birth: BirthInput) -> Chart:
        calculation_time = (
            _solar_time_datetime(birth)
            if self.use_true_solar_time
            else datetime(birth.year, birth.month, birth.day, birth.hour, birth.minute)
        )
        instant = _birth_instant(birth)
        year_stem, year_branch = year_pillar(instant)
        month_stem, month_branch = month_pillar(instant)
        day_date, hour_index = self._day_source(calculation_time)
        day = sxtwl.fromSolar(day_date.year, day_date.month, day_date.day)
        day_stem, day_branch = _gz_text(day.getDayGZ())
        hour_stem, hour_branch = _gz_text(day.getHourGZ(hour_index))
        values = (
            ("year", year_stem, year_branch),
            ("month", month_stem, month_branch),
            ("day", day_stem, day_branch),
            ("hour", hour_stem, hour_branch),
        )
        branch_values = tuple(branch for _, _, branch in values)
        pillars = tuple(
            Pillar(
                name=name,
                heavenly_stem=stem,
                earthly_branch=branch,
                hidden_stems=HIDDEN_STEMS[branch],
                ten_god=ten_god(day_stem, stem, is_day_pillar=name == "day"),
                na_yin=_na_yin(stem, branch),
            )
            for name, stem, branch in values
        )
        return Chart(
            birth=birth,
            pillars=pillars,
            day_master=day_stem,
            # 五行普查随命盘一起产出（Phase 5.3）。UI 直接读
            # chart.elements.{count,missing,dominant}，不再有「界面读了
            # 一个 provider 没产出过的键」那类死代码。facts 层调用同一个
            # element_census —— 两个消费者，一份口径。
            elements={
                "day_master_element": ELEMENTS[day_stem],
                **element_census(pillars),
            },
            # 胎元 / 空亡 / 十二长生（Phase 6.4）：无实质分歧的排盘派生量。
            auxiliary=auxiliary_of(
                month_stem, month_branch, day_stem, day_branch,
                tuple(branch for _, _, branch in values),
            ),
            relations=_relations(branch_values),
            provider=self.name,
            algorithm_version=self.algorithm_version,
        )
