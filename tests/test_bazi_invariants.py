"""Phase 1：第二实现式不变量测试与性能验收。

这里不复用 provider 内部任何推导，只按干支体系自身的第一性规则独立重算：
五虎遁（年干 → 月干）、五鼠遁（日干 → 时干）、六十甲子连续性、日柱逐日递进，
以及合法干支必须是同阴阳配对。

这些规则与 provider 的实现路径不同，所以能独立暴露历法层错误 —— 例如日柱
偏移一天、月干错位、六十甲子闭合失败。它们不依赖任何外部命盘数据库，
因此不会把「未核实的权威数据」当成事实。
"""

import time
from datetime import date, timedelta

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.ten_gods import BRANCHES, STEMS

PROVIDER = SxtwlBaziProvider()

# 验收线来自 MINGLI_PLAN.md Phase 1：单次排盘 < 100ms。
# 实测冷启动约 2.5ms、稳态约 0.3ms，留足余量以免在负载高的机器上抖动。
CALCULATION_BUDGET_SECONDS = 0.1


def pillars_of(birth: BirthInput):
    chart = PROVIDER.calculate(birth)
    return tuple((pillar.heavenly_stem, pillar.earthly_branch) for pillar in chart.pillars)


def cycle_index(stem: str, branch: str) -> int:
    """干支在六十甲子中的序号。"""
    return next(
        index for index in range(60)
        if index % 10 == STEMS.index(stem) and index % 12 == BRANCHES.index(branch)
    )


def five_tiger_escape(year_stem: str, month_branch: str) -> str:
    """五虎遁：寅月天干 = (年干序号 × 2 + 2) mod 10，再按离寅的位次推移。"""
    base = (STEMS.index(year_stem) * 2 + 2) % 10
    offset = (BRANCHES.index(month_branch) - BRANCHES.index("寅")) % 12
    return STEMS[(base + offset) % 10]


def five_rat_escape(day_stem: str, hour_branch: str) -> str:
    """五鼠遁：子时天干 = (日干序号 × 2) mod 10，再按离子的位次推移。"""
    base = (STEMS.index(day_stem) * 2) % 10
    return STEMS[(base + BRANCHES.index(hour_branch)) % 10]


# ── 干支合法性 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [1600, 1900, 2000, 2100, 2500])
def test_every_pillar_is_a_valid_sexagenary_pair(year):
    """六十甲子只含同阴阳配对；出现甲丑、乙子之类即说明组合逻辑有误。"""
    chart = PROVIDER.calculate(BirthInput(year, 6, 15, 12))

    for pillar in chart.pillars:
        assert STEMS.index(pillar.heavenly_stem) % 2 == BRANCHES.index(pillar.earthly_branch) % 2, (
            f"{pillar.name} 柱 {pillar.heavenly_stem}{pillar.earthly_branch} 不是合法干支"
        )


# ── 日柱：逐日递进与六十甲子闭合 ────────────────────────────────────────


def test_day_pillar_advances_by_exactly_one_each_day():
    """日柱必须每天在六十甲子里前进一步，不允许跳格或重复。"""
    day = date(1990, 6, 1)
    previous = None
    while day < date(1990, 8, 1):
        chart = PROVIDER.calculate(BirthInput(day.year, day.month, day.day, 12))
        current = cycle_index(chart.pillars[2].heavenly_stem, chart.pillars[2].earthly_branch)
        if previous is not None:
            assert current == (previous + 1) % 60, f"{day} 的日柱没有接上前一天"
        previous = current
        day += timedelta(days=1)


def test_day_pillar_closes_the_sixty_day_cycle():
    """相隔 60 天的日柱与时柱必须完全相同。"""
    first = pillars_of(BirthInput(1990, 6, 15, 12))
    later = pillars_of(BirthInput(1990, 8, 14, 12))

    assert first[2] == later[2]
    assert first[3] == later[3]


# ── 月干：五虎遁 ────────────────────────────────────────────────────────


def test_month_stem_follows_five_tiger_escape_across_a_whole_year():
    """一整年十二个月，月干都必须能由年干独立推出。"""
    for month in range(1, 13):
        chart = PROVIDER.calculate(BirthInput(1990, month, 20, 12))
        year_stem = chart.pillars[0].heavenly_stem
        month_stem = chart.pillars[1].heavenly_stem
        month_branch = chart.pillars[1].earthly_branch

        assert month_stem == five_tiger_escape(year_stem, month_branch), (
            f"1990-{month:02d}-20 的月干与五虎遁不符"
        )


def test_month_stem_follows_five_tiger_escape_for_every_year_stem():
    """十个年干都要覆盖到，避免只在某几个年干上碰巧成立。"""
    seen = set()
    for year in range(1990, 2000):
        chart = PROVIDER.calculate(BirthInput(year, 6, 20, 12))
        year_stem = chart.pillars[0].heavenly_stem
        seen.add(year_stem)
        assert chart.pillars[1].heavenly_stem == five_tiger_escape(
            year_stem, chart.pillars[1].earthly_branch
        )

    assert seen == set(STEMS)


# ── 时干：五鼠遁（23 时另有晚子时口径，单独覆盖）─────────────────────────


@pytest.mark.parametrize("hour", [0, 1, 2, 5, 9, 11, 12, 13, 17, 21, 22])
def test_hour_stem_follows_five_rat_escape(hour):
    chart = PROVIDER.calculate(BirthInput(1990, 6, 15, hour))
    day_stem = chart.pillars[2].heavenly_stem
    hour_stem = chart.pillars[3].heavenly_stem
    hour_branch = chart.pillars[3].earthly_branch

    assert hour_branch == BRANCHES[((hour + 1) // 2) % 12]
    assert hour_stem == five_rat_escape(day_stem, hour_branch)


def test_hour_branch_maps_the_full_day_onto_twelve_double_hours():
    """0-22 时正好覆盖十二个时辰：子只占 0 时，其余各占两小时。"""
    branches = [
        PROVIDER.calculate(BirthInput(1990, 6, 15, hour)).pillars[3].earthly_branch
        for hour in range(23)
    ]

    assert branches[0] == "子"
    assert branches[1] == branches[2] == "丑"
    assert branches[22] == "亥"
    assert set(branches) == set(BRANCHES)


def test_late_zi_hour_stem_uses_the_next_day_stem_by_default():
    """23 时属晚子时：默认口径下时干按**次日**日干推，日柱不动。"""
    late = PROVIDER.calculate(BirthInput(1990, 6, 15, 23))
    next_day = PROVIDER.calculate(BirthInput(1990, 6, 16, 12))

    assert late.pillars[3].earthly_branch == "子"
    assert late.pillars[3].heavenly_stem == five_rat_escape(
        next_day.pillars[2].heavenly_stem, "子"
    )


# ── 时区语义 ────────────────────────────────────────────────────────────


def test_absolute_instant_drives_year_and_month_but_local_time_drives_day_and_hour():
    """年月柱按绝对时刻判定；日柱、时柱按出生地当地民用时。

    1990-12-15 12:00（上海，UTC+8）与 1990-12-15 13:00（东京，UTC+9）
    是同一瞬间，因此年月柱必须一致；而当地时辰不同，时柱必须不同。
    """
    shanghai = BirthInput(1990, 12, 15, 12, 0, timezone="Asia/Shanghai")
    tokyo = BirthInput(1990, 12, 15, 13, 0, timezone="Asia/Tokyo")

    assert shanghai.instant() == tokyo.instant()
    assert pillars_of(shanghai)[:2] == pillars_of(tokyo)[:2]
    assert pillars_of(shanghai)[3] != pillars_of(tokyo)[3]


# ── 性能验收 ────────────────────────────────────────────────────────────


def test_warm_chart_calculation_is_within_budget():
    """验收：单次排盘 < 100ms（节气缓存命中后的稳态耗时）。"""
    birth = BirthInput(1990, 6, 15, 12)
    PROVIDER.calculate(birth)

    start = time.perf_counter()
    for _ in range(50):
        PROVIDER.calculate(birth)
    elapsed = (time.perf_counter() - start) / 50

    assert elapsed < CALCULATION_BUDGET_SECONDS, f"稳态单次排盘 {elapsed * 1000:.1f}ms 超出预算"


def test_cold_chart_calculation_is_within_budget():
    """验收：单次排盘 < 100ms（节气缓存未命中，含首次历法查询）。"""
    years = list(range(1900, 1930))

    start = time.perf_counter()
    for year in years:
        PROVIDER.calculate(BirthInput(year, 6, 15, 12))
    elapsed = (time.perf_counter() - start) / len(years)

    assert elapsed < CALCULATION_BUDGET_SECONDS, f"冷启动单次排盘 {elapsed * 1000:.1f}ms 超出预算"
