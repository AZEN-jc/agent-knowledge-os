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

#: ``datetime`` 能表示的年份范围。节气换算凡落在外面的都取不到 ——
#: 这不是保守，是硬边界：``datetime(0, …)`` 与 ``datetime(10000, …)``
#: 直接抛 ValueError。见 :func:`solar_terms` 的说明。
MIN_YEAR, MAX_YEAR = 1, 9999

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

#: 格里高利历在公历 1582-10-15 起施行。JD 小于这个值（约 2299160.5）时，
#: sxtwl 的 ``JD2DD`` 返回的是**儒略历**日期，而 Python 的 ``datetime`` 与
#: 用户的生辰输入都是**公历**。两者在 16 世纪相差 10 天、在公元 100 年相差
#: 2 天 —— 拿儒略日期去和公历的生辰比较，节气分界就会整体错位。
_GREGORIAN_ADOPTION_JD = 2299161


def _jd_to_gregorian(jd: float) -> tuple[int, int, int, int, int, int]:
    """把儒略日换成**公历**（proleptic Gregorian）年月日时分秒。

    **为什么不能用 sxtwl 的 ``JD2DD``。** 实测（Phase 3.1）：

    - ``JD2DD`` 对 JD < 2299161 的日期返回**儒略历**，之后才返回公历。
    - 偏移量与史实精确吻合：公元 100 年差 2 天、1500 年差 9 天、
      1581/1582 年差 10 天、1583 年起 0 天。
    - 于是 900 年与 1000 年（儒略历的闰年）会返回 **2 月 29 日**，
      而公历里这两年都不是闰年 —— ``datetime(900, 2, 29)`` 直接抛
      ``ValueError: day is out of range for month``。这正是 Phase 2 记录在案的
      6 个失败年（899–901、999–1001）。

    更要紧的不是崩溃，是**错标**：公历输入的生辰与儒略历标注的节气时刻
    相差最多 10 天，年月分界会整体偏移。所有 1583 年之前的命盘都受影响，
    而金标准案例全是 1990 年之后的，所以测试一直没抓到。

    本函数对任意 JD 一律走格里高利修正（不按 1582 分支），因此输出必是合法
    公历日期。算法取自 Meeus《Astronomical Algorithms》第 7 章，
    只用整数与浮点运算，不依赖第三方历法库 —— 排盘的历法部分不能外包。

    时刻口径：sxtwl 的 ``jd`` 给出的是**北京时间**（2024 立春为 16:26:53，
    与公开时刻一致），所以直接换算出的时分秒即为北京时间，调用方按
    ``SXTWL_ZONE`` 贴上固定 UTC+8。
    """
    z = int(jd + 0.5)
    fraction = (jd + 0.5) - z

    alpha = int((z - 1867216.25) / 36524.25)
    a = z + 1 + alpha - int(alpha / 4)
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)

    day_with_fraction = b - d - int(30.6001 * e) + fraction
    day = int(day_with_fraction)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715

    seconds_of_day = (day_with_fraction - day) * 86400
    hour = int(seconds_of_day // 3600)
    minute = int((seconds_of_day % 3600) // 60)
    second = int(seconds_of_day % 60)
    return year, month, day, hour, minute, second


@dataclass(frozen=True)
class SolarTerm:
    """一个节气的名称与绝对时刻。"""

    name: str
    moment: datetime


@lru_cache(maxsize=64)
def solar_terms(year: int) -> tuple[SolarTerm, ...]:
    """返回公历年 ``year`` 立春起、到次年立春为止的 25 个节气。

    时刻一律按北京标准时间（固定 UTC+8）解释，见模块 docstring。

    历法换算走 :func:`_jd_to_gregorian` 而不是 ``sxtwl.JD2DD`` ——
    后者对 1582 年前返回儒略历，见那个函数的说明。

    **落在 ``datetime`` 可表示范围（1–9999 年）之外的节气被丢弃。**
    ``getJieQiByYear(N)`` 的列表以次年立春收尾，于是 ``solar_terms(9999)``
    含第 10000 年的立春、``solar_terms(0)`` 含第 0 年的项，两者都会让
    ``datetime()`` 抛 ``year 0/10000 is out of range`` —— 这正是 Phase 3.1
    之前剩下的 3 个失败年（1、9998、9999）。丢掉的只是**用于跨年拼接的
    边界项**：同一个立春在下一年的调用里会再次出现，:func:`jie_terms_in`
    按绝对时刻去重，所以不会漏。
    """
    terms = []
    for entry in sxtwl.getJieQiByYear(year):
        year_, month_, day_, hour_, minute_, second_ = _jd_to_gregorian(entry.jd)
        if not MIN_YEAR <= year_ <= MAX_YEAR:
            continue
        terms.append(
            SolarTerm(
                name=JIEQI_NAMES[entry.jqIndex],
                moment=datetime(
                    year_, month_, day_, hour_, minute_, second_,
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

    调用方传进来的年份若超出 :data:`MIN_YEAR`–:data:`MAX_YEAR`，
    对应的一次 ``solar_terms`` 会返回空元组，这里自然跳过。
    """
    unique: dict[datetime, SolarTerm] = {}
    for year in years:
        for term in solar_terms(year):
            if term.name in JIE_TO_MONTH_BRANCH:
                unique.setdefault(term.moment, term)
    return tuple(sorted(unique.values(), key=lambda term: term.moment))


def previous_jie(moment: datetime) -> SolarTerm:
    """返回不晚于 ``moment`` 的最后一个「节」。

    只关心「之前」，所以只需要 ``moment`` 所在年与上一年的节气 ——
    一月初的时刻属于上一年的大寒/小寒，跨年那一个必须由上一年的列表提供。
    **不取次年**，因此 ``moment`` 在 :data:`MAX_YEAR` 年末也能算。
    """
    instant = as_instant(moment)
    terms = jie_terms_in((instant.year - 1, instant.year))
    candidates = [term for term in terms if term.moment <= instant]
    if not candidates:
        raise RuntimeError(
            f"找不到 {instant.isoformat()} 之前的节气；"
            f"该时刻可能早于历法库支持范围（{MIN_YEAR}–{MAX_YEAR}）。"
        )
    return max(candidates, key=lambda term: term.moment)


def surrounding_jie(moment: datetime) -> tuple[SolarTerm, SolarTerm]:
    """返回 ``moment`` 之前最近的节与之后最近的节。

    需要「之后」，因此要取次年的节气 —— 于是 ``moment`` 落在
    :data:`MAX_YEAR` 最后几个月时，下一个节已超出 ``datetime`` 能表示的
    范围，只能如实报错。要「之前」的调用方请用 :func:`previous_jie`，
    它在年末照样能算。
    """
    instant = as_instant(moment)
    terms = jie_terms_in((instant.year - 1, instant.year, instant.year + 1))
    before = [term for term in terms if term.moment <= instant]
    after = [term for term in terms if term.moment > instant]
    if not before:
        raise RuntimeError(
            f"找不到 {instant.isoformat()} 之前的节气；"
            f"该时刻可能早于历法库支持范围（{MIN_YEAR}–{MAX_YEAR}）。"
        )
    if not after:
        raise RuntimeError(
            f"找不到 {instant.isoformat()} 之后的节气；"
            f"{MAX_YEAR} 年末之后的节气已超出 datetime 可表示范围。"
        )
    return max(before, key=lambda term: term.moment), min(after, key=lambda term: term.moment)


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
    return JIE_TO_MONTH_BRANCH[previous_jie(moment).name]


def month_pillar(moment: datetime) -> tuple[str, str]:
    """返回 ``moment`` 的月柱干支；月干由年干按五虎遁推出。"""
    year_stem = year_pillar(moment)[0]
    branch = month_branch(moment)
    # 五虎遁：甲己之年丙作首 → 寅月天干序号 = (年干序号 × 2 + 2) mod 10
    yin_stem_index = (STEMS.index(year_stem) * 2 + 2) % 10
    # 月序从寅起算，绕回丑（子、丑在寅之前，必须对 12 取模）
    offset = (BRANCHES.index(branch) - BRANCHES.index("寅")) % 12
    return STEMS[(yin_stem_index + offset) % 10], branch
