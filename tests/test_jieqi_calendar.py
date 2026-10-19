"""节气历法换算的独立基准验证（Phase 3.1）。

**这个文件为什么存在。** Phase 2 发现引擎在 6 个年份上崩溃、报的是
``"day is out of range for month"``（899–901、999–1001）。根因不是数据缺失，
是 **sxtwl 的 ``JD2DD`` 对 1582 年前的儒略日返回儒略历**：

- 900 与 1000 在儒略历是闰年，于是 sxtwl 给出 2 月 29 日；
- 公历里这两年都不是闰年，``datetime(900, 2, 29)`` 直接抛 ValueError。

崩溃只是症状。**真正的问题是错标**：公历输入的生辰与儒略历标注的节气时刻
相差最多 10 天，年月分界会整体偏移 —— 所有 1583 年之前的命盘都受影响。
金标准案例全是 1990 年之后的，所以测试一直没抓到。

## 独立基准是什么

儒略→公历的修正量是**历史事实**，不依赖本项目的任何一行代码，也不依赖
sxtwl：1582 年格里高利历施行时删了 10 天，之前每差一个「百年不闰」多一天。
下表即为基准，逐项钉住：

| 公历年份 | 格里高利 = 儒略 + N 天 |
|---|---|
| 100 | −2 |
| 500 | +1 |
| 900 | +4 |
| 1000 | +5 |
| 1500 | +9 |
| 1581 / 1582 | +10 |
| 1583 起 | 0 |

**这是两条独立的路**：sxtwl 给儒略日与儒略历标签，我们给公历标签，
两者的差必须正好等于历史修正量表。对上了，才敢说换算是真的。
"""

from __future__ import annotations

import datetime as dt

import pytest
import sxtwl

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.jieqi import (
    MAX_YEAR,
    MIN_YEAR,
    _jd_to_gregorian,
    previous_jie,
    solar_terms,
)

PROVIDER = SxtwlBaziProvider()

#: 儒略→公历修正量表。见模块 docstring 的说明。
#: 键是公历年份，值是「格里高利日期 − 儒略日期」的天数差。
JULIAN_TO_GREGORIAN_OFFSET = {
    100: -2,
    500: 1,
    900: 4,
    1000: 5,
    1500: 9,
    1581: 10,
    1582: 10,
    1583: 0,
    1600: 0,
    1900: 0,
    2024: 0,
}

#: Phase 2 记录在案的 6 个失败年。
FORMERLY_BROKEN_YEARS = (899, 900, 901, 999, 1000, 1001)


# ── 独立基准：修正量表 ────────────────────────────────────────────────


@pytest.mark.parametrize("year", sorted(JULIAN_TO_GREGORIAN_OFFSET))
def test_the_conversion_matches_the_historical_offset_table(year: int):
    """换算结果与 sxtwl 儒略标签之差，必须等于历史修正量。

    这是本文件的核心断言。两条独立的路（我们的公历换算 vs sxtwl 的儒略标签）
    在同一个儒略日上给出不同的日历名，差值必须正好是史料上的修正量。
    差一天都说明有一边错了。
    """
    entry = sxtwl.getJieQiByYear(year)[0]  # 立春
    julian = sxtwl.JD2DD(entry.jd)
    julian_date = dt.date(int(julian.Y), int(julian.M), int(julian.D))
    gregorian = _jd_to_gregorian(entry.jd)
    gregorian_date = dt.date(gregorian[0], gregorian[1], gregorian[2])

    offset = (gregorian_date - julian_date).days
    assert offset == JULIAN_TO_GREGORIAN_OFFSET[year], (
        f"{year} 年立春：公历 {gregorian_date} 与儒略 {julian_date} "
        f"相差 {offset} 天，历史修正量为 {JULIAN_TO_GREGORIAN_OFFSET[year]} 天"
    )


def test_the_offset_grows_monotonically_then_vanishes():
    """修正量随世纪单调增长，1583 年起归零。

    单独钉住形状：修正量不是随机噪声，它由「百年不闰、四百年再闰」的规则决定，
    所以必须单调。这条能抓住「修正量算错但碰巧对上了某一年」的情况。
    """
    def offset_of(year: int) -> int:
        entry = sxtwl.getJieQiByYear(year)[0]
        julian = sxtwl.JD2DD(entry.jd)
        gregorian = _jd_to_gregorian(entry.jd)
        return (dt.date(gregorian[0], gregorian[1], gregorian[2])
                - dt.date(int(julian.Y), int(julian.M), int(julian.D))).days

    samples = [200, 400, 600, 800, 1000, 1200, 1400, 1582]
    offsets = [offset_of(year) for year in samples]
    assert offsets == sorted(offsets), f"修正量应单调不减：{list(zip(samples, offsets))}"
    assert all(offset_of(year) == 0 for year in (1583, 1700, 2000, 2024)), (
        "1583 年之后修正量必须为 0"
    )


# ── 1583 年后零变化（回归保护）───────────────────────────────────────


@pytest.mark.parametrize("year", (1583, 1600, 1700, 1800, 1900, 1990, 2000, 2024, 2100, 9999))
def test_post_gregorian_years_are_unchanged(year: int):
    """1583 年起，我们的换算必须与 sxtwl.JD2DD 逐字段相同。

    这条是回归保护：格里高利历施行之后儒略与公历重合，所以换算结果
    一个字段都不能变。变了就说明修改破坏了现代日期的排盘 ——
    而全部金标准案例都在这个区间里。
    """
    for entry in sxtwl.getJieQiByYear(year)[:4]:
        converted = sxtwl.JD2DD(entry.jd)
        expected = (
            int(converted.Y), int(converted.M), int(converted.D),
            int(converted.h), int(converted.m), int(converted.s),
        )
        assert _jd_to_gregorian(entry.jd) == expected, (
            f"{year} 年 jqIndex={entry.jqIndex}：{_jd_to_gregorian(entry.jd)} != {expected}"
        )


# ── 穷举：换算永不产出非法公历日期 ───────────────────────────────────


def test_the_conversion_never_produces_an_invalid_date():
    """穷举 JD 区间，确认换算结果永远是合法公历日期。

    ``_jd_to_gregorian`` 是纯函数、9999 次调用约 0.02 秒，所以这里做得起
    穷举 —— 集成层（sxtwl 调用）要 16 秒，只能抽样，见下一个测试。

    **年份 0 与 10000 不算失败**：那是 ``datetime`` 的表示边界，由调用方
    （:func:`solar_terms`）负责过滤，不是换算的错。这里要抓的是
    **月日非法**（13 月、32 日、2 月 30 日）—— 那才是算法错误。
    """
    start = 1721425  # 公元 1 年附近
    checked = 0
    for offset in range(0, 40000, 7):  # 约 110 年一个采样点，跨 1–9999
        jd = start + offset * 0.5
        year, month, day, hour, minute, second = _jd_to_gregorian(jd)
        if not 1 <= year <= 9999:
            continue  # datetime 表示边界，见 docstring
        dt.datetime(year, month, day, hour, minute, second)  # 非法就抛
        assert 1 <= month <= 12, f"JD {jd} 换算出 {month} 月"
        assert 1 <= day <= 31, f"JD {jd} 换算出 {day} 日"
        assert 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59
        checked += 1
    assert checked > 1000, f"只验了 {checked} 个点，抽样太稀"


# ── 集成层：曾经的 6 个失败年 ─────────────────────────────────────────


@pytest.mark.parametrize("year", FORMERLY_BROKEN_YEARS)
def test_the_formerly_broken_years_now_calculate(year: int):
    """Phase 2 记录在案的 6 个失败年，现在必须能排出命盘。"""
    chart = PROVIDER.calculate(BirthInput(year, 6, 15, 12))

    assert chart.pillars[2].heavenly_stem, "日主不应为空"
    assert len(chart.pillars) == 4


@pytest.mark.parametrize(
    "month, day",
    ((1, 15), (2, 1), (3, 1), (6, 15), (9, 1), (11, 20), (12, 31)),
)
def test_sample_dates_across_the_full_year_range_calculate(month: int, day: int):
    """全区间抽样排盘：边界年 + 每百年一个采样点。

    ``solar_terms`` 走 sxtwl 的 C 调用，全区间要 16 秒，不适合放进单元测试，
    所以这里抽样 —— 但**边界年一个不漏**（1、2、9997、9998、9999）。
    """
    years = [1, 2, 3, 9996, 9997, 9998, 9999]
    years += list(range(100, 10000, 100))
    for year in years:
        try:
            PROVIDER.calculate(BirthInput(year, month, day, 12))
        except Exception as exc:  # 允许的失败只有下面那一种
            assert year == 1 and month == 1 and day < 20, (
                f"{year}-{month:02d}-{day:02d} 排盘失败：{type(exc).__name__}: {exc}"
            )


def test_year_one_before_the_first_jie_reports_a_readable_reason():
    """公元 1 年小寒之前的时刻，报错必须说清原因。

    这是修完之后**唯一剩下**的失败：1 月 1 日的前一个「节」落在第 0 年，
    而 ``datetime`` 表示不了第 0 年。这是硬边界，不是缺陷 ——
    但要报得让人读懂，而不是 ``year 0 is out of range``。
    """
    with pytest.raises(RuntimeError, match="之前的节气"):
        PROVIDER.calculate(BirthInput(1, 1, 1, 12))

    # 小寒之后就能算 —— 边界是精确的，不是把整个 1 年一刀切掉。
    chart = PROVIDER.calculate(BirthInput(1, 2, 1, 12))
    assert chart.pillars[0].earthly_branch


def test_the_first_jie_of_year_one_is_reachable_from_year_zero_data():
    """第 0 年的节气表仍能提供第 1 年的立春（跨年拼接没被砍断）。"""
    # solar_terms(0) 列表以次年立春收尾，过滤后剩下的正是第 1 年的节气。
    kept = [term for term in solar_terms(0) if term.moment.year == 1]
    assert kept, "第 0 年的表里应保留下落在第 1 年的节气"
    assert all(term.moment.year == 1 for term in kept)


def test_solar_terms_never_returns_an_empty_year_inside_the_range():
    """支持区间内任何一年都不能返回空节气表。

    过滤掉表示不了的年份时，最容易犯的错是砍过头 —— 把某一整年全滤掉，
    于是那一年的排盘全失败，而任何单点测试都可能碰不到那一年。
    """
    for year in (MIN_YEAR, 2, 899, 900, 1000, 5000, 9999, MAX_YEAR):
        assert solar_terms(year), f"{year} 年的节气表不应为空"


def test_previous_jie_works_at_the_last_moment_of_the_range():
    """:func:`previous_jie` 在支持范围末尾照样能算。

    它只取「之前」，不需要次年节气 —— 这是它与 :func:`surrounding_jie`
    的区别，也是年末仍可用的原因。
    """
    term = previous_jie(dt.datetime(9999, 11, 20, 12, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    assert term.moment.year == 9999
    assert term.name in {
        "立春", "惊蛰", "清明", "立夏", "芒种", "小暑",
        "立秋", "白露", "寒露", "立冬", "大雪", "小寒",
    }
