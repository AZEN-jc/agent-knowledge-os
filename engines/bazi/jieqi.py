"""节气精确时刻，以及由它决定的干支年、月分界。

sxtwl 的 ``getYearGZ()`` / ``getMonthGZ()`` 只按**日期**分界：立春当天
00:00 就换年，芒种当天 00:00 就换月。传统规则是按节气的**精确时刻**分界，
于是节气日当天、节气时刻之前出生的人会拿到错的年柱和月柱。本模块自己取
节气时刻来判断，不沿用 sxtwl 的干支结果。

时刻语义：节气是天文事件，对应唯一的绝对时刻。sxtwl 给出的是北京时间
（UTC+8），这里统一按绝对时刻比较，所以出生时刻的时区不会污染节气判断；
真太阳时只影响日柱和时柱，不影响年月分界。这是本项目的显式选择，其他
流派若按当地视时比较节气，属于另一套口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import sxtwl

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

BEIJING = ZoneInfo("Asia/Shanghai")

# sxtwl 的 jqIndex → 节气名。0=冬至，1=小寒，2=大寒，3=立春，依此类推。
JIEQI_NAMES = (
    "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明",
    "谷雨", "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋",
    "处暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
)

# 十二「节」（不含中气）：每个节开启一个月支。
JIE_TO_MONTH_BRANCH = {
    "立春": "寅", "惊蛰": "卯", "清明": "辰", "立夏": "巳", "芒种": "午", "小暑": "未",
    "立秋": "申", "白露": "酉", "寒露": "戌", "立冬": "亥", "大雪": "子", "小寒": "丑",
}

LICHUN = "立春"


@dataclass(frozen=True)
class SolarTerm:
    """一个节气的名称与绝对时刻。"""

    name: str
    moment: datetime


@lru_cache(maxsize=64)
def solar_terms(year: int) -> tuple[SolarTerm, ...]:
    """返回公历年 ``year`` 立春起、到次年立春为止的 25 个节气。"""
    terms = []
    for entry in sxtwl.getJieQiByYear(year):
        converted = sxtwl.JD2DD(entry.jd)
        terms.append(
            SolarTerm(
                name=JIEQI_NAMES[entry.jqIndex],
                moment=datetime(
                    int(converted.Y), int(converted.M), int(converted.D),
                    int(converted.h), int(converted.m), int(converted.s),
                    tzinfo=BEIJING,
                ),
            )
        )
    return tuple(terms)


def _as_instant(moment: datetime) -> datetime:
    """无时区的时刻按北京时间解释；已带时区的原样返回。"""
    return moment if moment.tzinfo else moment.replace(tzinfo=BEIJING)


def lichun_moment(year: int) -> datetime:
    """返回公历年 ``year`` 立春的精确时刻。"""
    for term in solar_terms(year):
        if term.name == LICHUN and term.moment.year == year:
            return term.moment
    raise RuntimeError(f"未能从 sxtwl 取得 {year} 年立春时刻。")


def ganzhi_year(moment: datetime) -> int:
    """返回 ``moment`` 所属的干支年（以立春为界的公历年数字）。"""
    instant = _as_instant(moment)
    return instant.year if instant >= lichun_moment(instant.year) else instant.year - 1


def year_pillar(moment: datetime) -> tuple[str, str]:
    """返回 ``moment`` 的年柱干支。"""
    index = (ganzhi_year(moment) - 4) % 60
    return STEMS[index % 10], BRANCHES[index % 12]


def month_branch(moment: datetime) -> str:
    """返回 ``moment`` 所属的月支：取不晚于该时刻的最后一个「节」。"""
    instant = _as_instant(moment)
    candidates = [
        term
        for year in (instant.year - 1, instant.year, instant.year + 1)
        for term in solar_terms(year)
        if term.name in JIE_TO_MONTH_BRANCH and term.moment <= instant
    ]
    if not candidates:
        raise RuntimeError(f"未能为 {instant} 定位所属月支。")
    return JIE_TO_MONTH_BRANCH[max(candidates, key=lambda term: term.moment).name]


def month_pillar(moment: datetime) -> tuple[str, str]:
    """返回 ``moment`` 的月柱干支；月干由年干按五虎遁推出。"""
    year_stem = year_pillar(moment)[0]
    branch = month_branch(moment)
    # 五虎遁：甲己之年丙作首 → 寅月天干序号 = (年干序号 × 2 + 2) mod 10
    yin_stem_index = (STEMS.index(year_stem) * 2 + 2) % 10
    # 月序从寅起算，绕回丑（子、丑在寅之前，必须对 12 取模）
    offset = (BRANCHES.index(branch) - BRANCHES.index("寅")) % 12
    return STEMS[(yin_stem_index + offset) % 10], branch
