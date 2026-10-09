"""Phase 1：第二实现 differential testing（lunar-python 交叉校验）。

sxtwl 与 lunar-python 是两套彼此独立的历法实现。这里逐日比对四柱，把
「我们的历法层有没有算错」从「看起来对」变成可证伪的问题 —— 单个实现里的
系统性偏差（日柱偏移一天、月干错位、节气归属错位）都会被另一套实现照出来。

口径映射：
- 年柱 ↔ ``getYearInGanZhiExact()``：以立春**时刻**为界（非正月初一）
- 月柱 ↔ ``getMonthInGanZhiExact()``：以节**时刻**为界
- 日柱 ↔ ``getDayInGanZhiExact2()``：晚子时算当天，对应我们的 ``no_roll``
- 时柱 ↔ ``getTimeInGanZhi()``

已知且显式的口径差异：lunar-python 拿墙上时间直接比节气表，不建模中国
1986-1991 年的夏令时；我们按绝对时刻比较。所以全量逐日比对只在**非夏令时
年份**做，夏令时年份用定点用例单独覆盖（见本文件末尾与 test_jieqi.py）。
"""

from datetime import date, timedelta

import pytest
from lunar_python import Solar

from engines.bazi import BirthInput, SxtwlBaziProvider

PROVIDER = SxtwlBaziProvider()
ROLLING_PROVIDER = SxtwlBaziProvider(late_zi_policy="roll")

# 中国 1986-1991 年实行夏令时（UTC+9）。lunar-python 不建模这段历史，
# 因此这些年份不参与逐日比对。
DST_YEARS = frozenset(range(1986, 1992))

DIFFERENTIAL_YEARS = [1975, 1985, 1995, 2005, 2024]


def ours(year: int, month: int, day: int, hour: int, minute: int = 0, *, roll: bool = False):
    provider = ROLLING_PROVIDER if roll else PROVIDER
    chart = provider.calculate(BirthInput(year, month, day, hour, minute))
    return ["".join((pillar.heavenly_stem, pillar.earthly_branch)) for pillar in chart.pillars]


def theirs(year: int, month: int, day: int, hour: int, minute: int = 0):
    lunar = Solar.fromYmdHms(year, month, day, hour, minute, 0).getLunar()
    return [
        lunar.getYearInGanZhiExact(),
        lunar.getMonthInGanZhiExact(),
        lunar.getDayInGanZhiExact2(),
        lunar.getTimeInGanZhi(),
    ]


def test_differential_years_do_not_overlap_the_dst_era():
    """逐日比对依赖「两套实现的墙上时间比较等价」，夏令时年份必须排除。"""
    assert DST_YEARS.isdisjoint(DIFFERENTIAL_YEARS)


@pytest.mark.parametrize("year", DIFFERENTIAL_YEARS)
def test_four_pillars_match_lunar_python_day_by_day(year):
    mismatches = []
    current = date(year, 1, 1)
    while current.year == year:
        mine = ours(current.year, current.month, current.day, 12)
        reference = theirs(current.year, current.month, current.day, 12)
        if mine != reference:
            mismatches.append((current.isoformat(), mine, reference))
        current += timedelta(days=1)

    assert mismatches == [], f"{year} 年有 {len(mismatches)} 天与 lunar-python 不一致：{mismatches[:3]}"


@pytest.mark.parametrize("year", [1975, 2024])
def test_hour_pillars_match_lunar_python_across_the_clock(year):
    """逐时覆盖 0-22 时；23 时是晚子时，另有专门用例。"""
    for hour in range(23):
        mine = ours(year, 12, 15, hour)[3]
        reference = theirs(year, 12, 15, hour)[3]
        assert mine == reference, f"{year}-12-15 {hour} 时的时柱不一致"


def test_month_pillars_match_lunar_python_across_a_year_of_hours():
    """把一整年每个节令前后的钟点都走一遍，覆盖十二次换月。"""
    for month in range(1, 13):
        for day in (5, 6, 7, 20):
            for hour in (0, 6, 12, 18):
                mine = ours(2024, month, day, hour)[1]
                reference = theirs(2024, month, day, hour)[1]
                assert mine == reference, f"2024-{month:02d}-{day:02d} {hour} 时的月柱不一致"


# ── 晚子时：两套实现的两种口径必须一一对上 ──────────────────────────────


def test_late_zi_policies_map_onto_lunar_python_exact_and_exact2():
    """lunar-python 的 Exact2 = 晚子时算当天，Exact = 算明天。"""
    lunar = Solar.fromYmdHms(1990, 6, 15, 23, 30, 0).getLunar()

    assert lunar.getDayInGanZhiExact2() == "辛亥"
    assert lunar.getDayInGanZhiExact() == "壬子"
    assert ours(1990, 6, 15, 23, 30)[2] == "辛亥"
    assert ours(1990, 6, 15, 23, 30, roll=True)[2] == "壬子"


def test_hour_pillar_at_late_zi_matches_lunar_python():
    """两套实现的晚子时时柱都是次日子时，分歧只在日柱。"""
    reference = theirs(1990, 6, 15, 23, 30)

    assert ours(1990, 6, 15, 23, 30)[3] == reference[3]
    assert ours(1990, 6, 15, 23, 30, roll=True)[3] == reference[3]


# ── 夏令时年份：差异必须是已知的、可解释的，而不是被掩盖 ─────────────────


def test_dst_era_divergence_is_known_and_explained():
    """1990-06-06 07:00 上海钟面 = 06:00 北京标准时；芒种在 06:46 标准时。

    按绝对时刻比较仍是巳月（我们）；按墙上时间直接比节气表则是午月
    （lunar-python，它不建模夏令时）。这个差异是有意选择的，不是缺陷。
    """
    assert ours(1990, 6, 6, 7)[1] == "辛巳"
    assert theirs(1990, 6, 6, 7)[1] == "壬午"
    # 钟面再往后一小时，两套实现重新一致
    assert ours(1990, 6, 6, 8)[1] == theirs(1990, 6, 6, 8)[1] == "壬午"
