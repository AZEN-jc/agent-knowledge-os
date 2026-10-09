"""节气精确时刻，以及由它决定的干支年、月分界。

sxtwl 的 ``getYearGZ()`` / ``getMonthGZ()`` 只按**日期**分界：立春当天
00:00 就换年，芒种当天 00:00 就换月。传统规则是按节气的**精确时刻**分界，
于是节气日当天、节气时刻之前出生的人会拿到错的年柱和月柱。本模块自己取
节气时刻来判断，不沿用 sxtwl 的干支结果。

时刻语义：节气是天文事件，对应唯一的绝对时刻。sxtwl 给出的是**北京标准时间
（固定 UTC+8）**的天文换算结果，不含历史夏令时，所以这里必须用固定 +08:00
去还原绝对时刻 —— 不能用 ``ZoneInfo("Asia/Shanghai")``，否则 1986-1991 年夏季
会被 tzdata 当作 UTC+9，把节气时刻整体挪前一小时。

出生时刻则按出生地当地**民用时**解释（含历史夏令时），两边都归到绝对时刻上
比较。因此时区会真实影响年月分界：同一墙上时间在东京与上海出生，可能落在
不同的干支年、月。这是有意为之，不是噪声。真太阳时只影响日柱和时柱，
不影响年月分界。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import sxtwl

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

# 解释**用户输入的墙上时间**时用：带历史夏令时的当地民用时。
BEIJING = ZoneInfo("Asia/Shanghai")

# 解释 **sxtwl 输出**时用：北京标准时间，固定 UTC+8，不含夏令时。
SXTWL_ZONE = timezone(timedelta(hours=8))

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
    """返回公历年 ``year`` 立春起、到次年立春为止的 25 个节气。

    时刻一律按北京标准时间（固定 UTC+8）解释，见模块 docstring。
    """
    terms = []
    for entry in sxtwl.getJieQiByYear(year):
        converted = sxtwl.JD2DD(entry.jd)
        terms.append(
            SolarTerm(
                name=JIEQI_NAMES[entry.jqIndex],
                moment=datetime(
                    int(converted.Y), int(converted.M), int(converted.D),
                    int(converted.h), int(converted.m), int(converted.s),
                    tzinfo=SXTWL_ZONE,
                ),
            )
        )
    return tuple(terms)


def as_instant(moment: datetime) -> datetime:
    """无时区的时刻按北京时间解释；已带时区的原样返回。"""
    return moment if moment.tzinfo else moment.replace(tzinfo=BEIJING)


def lichun_moment(year: int) -> datetime:
    """返回公历年 ``year`` 立春的精确时刻。"""
    for term in solar_terms(year):
        if term.name == LICHUN and term.moment.year == year:
            return term.moment
    raise RuntimeError(f"未能从 sxtwl 取得 {year} 年立春时刻。")


def jie_terms_in(years: Iterable[int]) -> tuple[SolarTerm, ...]:
    """返回若干公历年覆盖的十二「节」，按时刻排序并按绝对时刻去重。

    ``solar_terms`` 的结果在相邻年份之间重叠（上一年的列表以次年立春收尾），
    直接拼接会得到重复的节，进而算出零长度的月份，所以这里必须去重。
    """
    unique: dict[datetime, SolarTerm] = {}
    for year in years:
        for term in solar_terms(year):
            if term.name in JIE_TO_MONTH_BRANCH:
                unique.setdefault(term.moment, term)
    return tuple(sorted(unique.values(), key=lambda term: term.moment))


def surrounding_jie(moment: datetime) -> tuple[SolarTerm, SolarTerm]:
    """返回 ``moment`` 之前最近的节与之后最近的节。"""
    instant = as_instant(moment)
    terms = jie_terms_in((instant.year - 1, instant.year, instant.year + 1))
    previous = max(
        (term for term in terms if term.moment <= instant),
        key=lambda term: term.moment,
    )
    following = min(
        (term for term in terms if term.moment > instant),
        key=lambda term: term.moment,
    )
    return previous, following


def ganzhi_year(moment: datetime) -> int:
    """返回 ``moment`` 所属的干支年（以立春为界的公历年数字）。"""
    instant = as_instant(moment)
    return instant.year if instant >= lichun_moment(instant.year) else instant.year - 1


def year_pillar(moment: datetime) -> tuple[str, str]:
    """返回 ``moment`` 的年柱干支。"""
    index = (ganzhi_year(moment) - 4) % 60
    return STEMS[index % 10], BRANCHES[index % 12]


def month_branch(moment: datetime) -> str:
    """返回 ``moment`` 所属的月支：取不晚于该时刻的最后一个「节」。"""
    previous, _ = surrounding_jie(moment)
    return JIE_TO_MONTH_BRANCH[previous.name]


def month_pillar(moment: datetime) -> tuple[str, str]:
    """返回 ``moment`` 的月柱干支；月干由年干按五虎遁推出。"""
    year_stem = year_pillar(moment)[0]
    branch = month_branch(moment)
    # 五虎遁：甲己之年丙作首 → 寅月天干序号 = (年干序号 × 2 + 2) mod 10
    yin_stem_index = (STEMS.index(year_stem) * 2 + 2) % 10
    # 月序从寅起算，绕回丑（子、丑在寅之前，必须对 12 取模）
    offset = (BRANCHES.index(branch) - BRANCHES.index("寅")) % 12
    return STEMS[(yin_stem_index + offset) % 10], branch
