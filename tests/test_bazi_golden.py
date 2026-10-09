"""Phase 1：golden case 与 differential comparison 测试。"""

import pytest
from lunar_python import Solar

from engines.bazi import SxtwlBaziProvider
from engines.bazi.golden import GoldenCase, assert_chart_matches, compare_chart
from engines.bazi.golden_cases import GOLDEN_CASES
from tests.test_bazi_engine_contract import FixtureProvider, birth, chart_for


def case(expected=None) -> GoldenCase:
    return GoldenCase(
        case_id="fixture-001",
        birth=birth(),
        expected=expected or {"day_master": "戊"},
        source="local fixture; not an authoritative calculation",
    )


def test_golden_case_requires_identity_source_and_expected_values():
    with pytest.raises(ValueError, match="case_id"):
        GoldenCase("", birth(), {"day_master": "戊"}, "fixture")
    with pytest.raises(ValueError, match="source"):
        GoldenCase("case", birth(), {"day_master": "戊"}, "")
    with pytest.raises(ValueError, match="expected"):
        GoldenCase("case", birth(), {}, "fixture")


def test_compare_chart_returns_no_difference_for_matching_fields():
    chart = chart_for(birth())

    assert compare_chart(chart, case().expected) == []


def test_compare_chart_compares_pillars_as_serializable_values():
    chart = chart_for(birth())

    assert compare_chart(
        chart,
        {
            "pillars": [
                {"name": "year", "heavenly_stem": "甲", "earthly_branch": "子"},
                {"name": "month", "heavenly_stem": "丙", "earthly_branch": "寅"},
                {"name": "day", "heavenly_stem": "戊", "earthly_branch": "午"},
                {"name": "hour", "heavenly_stem": "壬", "earthly_branch": "申"},
            ]
        },
    ) == []


def test_assert_chart_matches_explains_mismatch_and_source():
    chart = FixtureProvider().calculate(birth())

    with pytest.raises(AssertionError, match=r"fixture-001.*local fixture"):
        assert_chart_matches(chart, case({"day_master": "甲"}))


# ── 双实现交叉确认的 golden cases ───────────────────────────────────────


def test_golden_cases_cover_the_phase_one_boundaries():
    case_ids = {golden.case_id for golden in GOLDEN_CASES}

    assert len(GOLDEN_CASES) >= 10
    assert len(case_ids) == len(GOLDEN_CASES)
    assert all(golden.source.strip() for golden in GOLDEN_CASES)


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=lambda item: item.case_id)
def test_golden_case_matches_our_implementation(golden):
    chart = SxtwlBaziProvider().calculate(golden.birth)

    assert_chart_matches(chart, golden)


@pytest.mark.parametrize("golden", GOLDEN_CASES, ids=lambda item: item.case_id)
def test_golden_case_provenance_is_reproducible(golden):
    """来源标注必须可复现：lunar-python 得给出同样的四柱。

    这条把「双实现交叉确认」从一句注释变成可证伪的断言 —— 两套实现一旦分叉，
    这里就会变红，而不是带着一个失效的来源标注继续跑。
    """
    birth_input = golden.birth
    lunar = Solar.fromYmdHms(
        birth_input.year, birth_input.month, birth_input.day,
        birth_input.hour, birth_input.minute, 0,
    ).getLunar()
    reference = [
        lunar.getYearInGanZhiExact(),
        lunar.getMonthInGanZhiExact(),
        lunar.getDayInGanZhiExact2(),
        lunar.getTimeInGanZhi(),
    ]
    chart = SxtwlBaziProvider().calculate(birth_input)

    assert [
        pillar.heavenly_stem + pillar.earthly_branch for pillar in chart.pillars
    ] == reference
