"""基于 sxtwl 的四柱 provider。

边界说明：sxtwl 负责天文历法和干支计算；本适配器只负责把结果转成项目
模型。大运、格局、用神和流派规则不在这里实现，避免把历法结果与命理解释混为一谈。

年柱和月柱不取 sxtwl 的 ``getYearGZ()`` / ``getMonthGZ()`` —— 那两个接口只按
**日期**分界（立春当天 00:00 就换年），节气日当天、节气时刻之前出生的人会拿到
错的年月柱。这里改由 :mod:`engines.bazi.jieqi` 按节气精确时刻判定。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sxtwl

from engines.bazi.jieqi import month_pillar, year_pillar
from engines.bazi.models import BirthInput, Chart, Pillar

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

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

ELEMENTS = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土",
    "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}

NA_YIN = (
    "海中金", "炉中火", "大林木", "路旁土", "剑锋金", "山头火", "涧下水", "城头土",
    "白蜡金", "杨柳木", "泉中水", "屋上土", "霹雳火", "松柏木", "长流水", "砂中金",
    "山下火", "平地木", "壁上土", "金箔金", "覆灯火", "天河水", "大驿土", "钗钏金",
    "桑柘木", "大溪水", "沙中土", "天上火", "石榴木", "大海水",
)

POLARITY = {
    "甲": "阳", "乙": "阴", "丙": "阳", "丁": "阴", "戊": "阳", "己": "阴",
    "庚": "阳", "辛": "阴", "壬": "阳", "癸": "阴",
}
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

BRANCH_RELATIONS = {
    "六合": {frozenset(pair) for pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")},
    "六冲": {frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")},
    "六害": {frozenset(pair) for pair in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")},
    "相破": {frozenset(pair) for pair in ("子酉", "寅亥", "卯午", "辰丑", "巳申", "未戌")},
}
SELF_PUNISHMENT = {"辰", "午", "酉", "亥"}
MUTUAL_PUNISHMENT = {frozenset(pair) for pair in ("丑戌未", "寅巳申")}


def _ten_god(day_master: str, stem: str, *, is_day_pillar: bool = False) -> str:
    """按日主五行、生克和阴阳计算天干十神。"""
    if is_day_pillar:
        return "日主"
    master_element = ELEMENTS[day_master]
    stem_element = ELEMENTS[stem]
    same_polarity = POLARITY[day_master] == POLARITY[stem]
    if stem_element == master_element:
        return "比肩" if same_polarity else "劫财"
    if stem_element == GENERATES[master_element]:
        return "食神" if same_polarity else "伤官"
    if master_element == GENERATES[stem_element]:
        return "偏印" if same_polarity else "正印"
    if stem_element == CONTROLS[master_element]:
        return "偏财" if same_polarity else "正财"
    return "七杀" if same_polarity else "正官"


def _gz_text(gz: object) -> tuple[str, str]:
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
    standard_meridian = local.utcoffset().total_seconds() / 3600 * 15
    longitude_minutes = (birth.longitude - standard_meridian) * 4
    equation_minutes = _equation_of_time_minutes(local.timetuple().tm_yday)
    return local + timedelta(minutes=longitude_minutes + equation_minutes)


def _birth_instant(birth: BirthInput) -> datetime:
    """出生时刻的绝对时间。

    节气是天文事件，只能按绝对时刻比较；民用时与真太阳时的差别属于另一层，
    不参与年月分界判定。
    """
    return datetime(
        birth.year, birth.month, birth.day, birth.hour, birth.minute,
        tzinfo=ZoneInfo(birth.timezone),
    )


class SxtwlBaziProvider:
    """sxtwl 2.x 的四柱适配器。"""

    name = "sxtwl"
    algorithm_version = "sxtwl-2.0.7-bazi-v2"
    supports_true_solar_time = True
    supports_dayun = False
    supports_relations = True

    def __init__(self, *, use_true_solar_time: bool = False) -> None:
        self.use_true_solar_time = use_true_solar_time

    def calculate(self, birth: BirthInput) -> Chart:
        calculation_time = (
            _solar_time_datetime(birth)
            if self.use_true_solar_time
            else datetime(birth.year, birth.month, birth.day, birth.hour, birth.minute)
        )
        day = sxtwl.fromSolar(
            calculation_time.year, calculation_time.month, calculation_time.day
        )
        instant = _birth_instant(birth)
        year_stem, year_branch = year_pillar(instant)
        month_stem, month_branch = month_pillar(instant)
        day_stem, day_branch = _gz_text(day.getDayGZ())
        hour_stem, hour_branch = _gz_text(day.getHourGZ(calculation_time.hour))
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
                ten_god=_ten_god(day_stem, stem, is_day_pillar=name == "day"),
                na_yin=_na_yin(stem, branch),
            )
            for name, stem, branch in values
        )
        return Chart(
            birth=birth,
            pillars=pillars,
            day_master=day_stem,
            elements={"day_master_element": ELEMENTS[day_stem]},
            relations=_relations(branch_values),
            provider=self.name,
            algorithm_version=self.algorithm_version,
        )
