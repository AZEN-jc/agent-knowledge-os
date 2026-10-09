"""Phase 1 验收：与 HeiGe-SuanMing 的排盘预期一致。

预期值取自 HeiGe-SuanMing（github.com/HeiGeAi/HeiGe-SuanMing）的
``tests/test_paipan.py``。这是**外部实现的口径对照**，不只是自洽性检查 ——
该仓库的排盘同样以 lunar_python 为历法底座，与我们的 sxtwl 路线相互独立。

来源快照：2026-10-09 浅克隆，其自带套件 ``Ran 158 tests ... OK``。
下面每个用例的 docstring 都标了对应的 HeiGe 测试类/方法名，便于回溯。

**明确忽略的差异（口径不同，不是缺陷）**：
- 起运日期的精度口径。本项目按「三日折一年」折算到日，HeiGe 另有取整方式，
  两者起运年一致（1997）但具体日期可能相差数日。因此这里只断言起运年与虚岁，
  不假装两边能对上同一天。
- 神煞、十神强弱、五行力量、命宫身宫等本阶段尚未实现的输出不在对照范围内。
"""

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.time_engine import ClassicalApproxDayunPolicy, sexagenary_year

PROVIDER = SxtwlBaziProvider()
TRUE_SOLAR_PROVIDER = SxtwlBaziProvider(use_true_solar_time=True)
ROLLING_PROVIDER = SxtwlBaziProvider(late_zi_policy="roll")

HEIGE_SOURCE = "HeiGe-SuanMing tests/test_paipan.py（2026-10-09 快照，158 tests OK）"


def pillars(birth: BirthInput, provider: SxtwlBaziProvider = PROVIDER) -> list[str]:
    return [
        pillar.heavenly_stem + pillar.earthly_branch
        for pillar in provider.calculate(birth).pillars
    ]


# ── 立春换年柱 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("day", "expected"),
    [(3, ["己卯", "丁丑"]), (5, ["庚辰", "戊寅"])],
)
def test_lichun_boundary_matches_heige(day, expected):
    """HeiGe TestIntegrationLiChunBoundary：2000 立春在 2/4。"""
    assert pillars(BirthInput(2000, 2, day, 12, 0))[:2] == expected


# ── 子时流派 ────────────────────────────────────────────────────────────


def test_late_zi_sects_match_heige():
    """HeiGe TestZiShiPin / TestIntegrationZiSect：2000-06-01 23:30。

    HeiGe 的 zi_sect=2（不换日）对应我们的 ``no_roll``，
    zi_sect=1（晚子换日）对应 ``roll``。两个口径的时柱都是戊子（取自次日辛卯日），
    分歧只在日柱 —— 与我们的实现一致。
    """
    late = BirthInput(2000, 6, 1, 23, 30)

    assert pillars(late) == ["庚辰", "辛巳", "庚寅", "戊子"]
    assert pillars(late, ROLLING_PROVIDER) == ["庚辰", "辛巳", "辛卯", "戊子"]


# ── 四柱样例 ────────────────────────────────────────────────────────────


def test_readme_sample_four_pillars_matches_heige():
    """HeiGe TestIntegrationSample：README 样例 1990-05-15 14:30 男。"""
    assert pillars(BirthInput(1990, 5, 15, 14, 30, gender="男")) == [
        "庚午", "辛巳", "庚辰", "癸未",
    ]


# ── 大运顺逆与起运 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("gender", "expected"), [("男", "forward"), ("女", "backward")])
def test_dayun_direction_matches_heige(gender, expected):
    """HeiGe TestIntegrationDaYunDirection：庚午阳年男顺排、女逆排。"""
    chart = PROVIDER.calculate(BirthInput(1990, 5, 15, 14, 30, gender=gender))

    assert ClassicalApproxDayunPolicy().calculate(chart)[0]["direction"] == expected


def test_qiyun_year_and_xusui_match_heige():
    """HeiGe TestIntegrationQiYunXuSui：1990 年生、1997 起运 → 虚岁 8。

    只断言起运年与虚岁，不断言具体日期（见模块 docstring 的口径说明）。
    """
    chart = PROVIDER.calculate(BirthInput(1990, 5, 15, 14, 30, gender="男"))
    first = ClassicalApproxDayunPolicy().calculate(chart)[0]

    start_year = 1990 + int(first["start_age_years"])
    assert start_year == 1997
    assert start_year - 1990 + 1 == 8
    # 起运取的是出生后的下一个节
    assert first["start_boundary"] == "芒种"


# ── 流年 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("year", "expected"), [(2024, "甲辰"), (2025, "乙巳"), (1990, "庚午")]
)
def test_liunian_ganzhi_matches_heige(year, expected):
    """HeiGe TestIntegrationLiuNianLiChun：流年与年柱同一套立春分界。"""
    stem, branch, _ = sexagenary_year(year)

    assert stem + branch == expected


# ── 真太阳时不得移动年月分界 ────────────────────────────────────────────


def test_true_solar_time_does_not_move_the_solar_term_boundary():
    """HeiGe TestAuditTrueSolarBoundary：2024-02-04 16:45 经度 104.1。

    真太阳时会把 16:45 校到约 15:41，早于立春 16:26。若校正参与了年月分界，
    这里就会得到癸卯/乙丑；HeiGe 与本项目都要求它是甲辰/丙寅 ——
    即真太阳时只影响日柱和时柱。
    """
    birth = BirthInput(2024, 2, 4, 16, 45, longitude=104.1, gender="男")
    got = pillars(birth, TRUE_SOLAR_PROVIDER)

    assert got[:2] == ["甲辰", "丙寅"]
    assert got[3][1] == "申"
    # 关闭真太阳时后年月柱不变，进一步确认校正没有渗进分界判定
    assert pillars(birth)[:2] == ["甲辰", "丙寅"]


def test_overseas_timezone_uses_the_same_lichun_instant():
    """HeiGe test_overseas_timezone_uses_same_lichun_instant：UTC-5 的同一绝对时刻。"""
    before = BirthInput(2024, 2, 4, 3, 0, timezone="America/New_York")
    after = BirthInput(2024, 2, 4, 3, 45, timezone="America/New_York")

    assert pillars(before)[:2] == ["癸卯", "乙丑"]
    assert pillars(after)[:2] == ["甲辰", "丙寅"]


# ── 年份边界 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("year", [1600, 2200])
def test_year_range_boundaries_match_heige(year):
    """HeiGe TestYearBoundary：1600 与 2200 两个端点都必须能正常排盘。"""
    got = pillars(BirthInput(year, 6, 15, 12, 0))

    assert len(got) == 4
    assert all(got)


def test_heige_source_is_recorded():
    """来源标注必须留在代码里，便于回溯对照的是哪个快照。"""
    assert "HeiGe-SuanMing" in HEIGE_SOURCE
    assert "158" in HEIGE_SOURCE
