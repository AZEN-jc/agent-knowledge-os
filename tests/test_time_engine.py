"""Time Engine 的确定性流年、大运与流月测试。"""

from datetime import datetime
from itertools import pairwise

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.jieqi import lichun_moment
from engines.bazi.time_engine import (
    ClassicalApproxDayunPolicy,
    DayunPolicy,
    flow_months,
    month_contexts,
    sexagenary_year,
    start_age_parts,
    year_contexts,
)


def chart():
    return SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12))


def dayun(birth, **kwargs):
    return ClassicalApproxDayunPolicy().calculate(
        SxtwlBaziProvider(**kwargs).calculate(birth)
    )


def test_sexagenary_year_known_cases():
    assert sexagenary_year(1984) == ("甲", "子", 0)
    assert sexagenary_year(2024) == ("甲", "辰", 40)


def test_year_contexts_are_reproducible_and_provider_traced():
    contexts = year_contexts(chart(), 2024, 2026)
    assert [(item.heavenly_stem, item.earthly_branch) for item in contexts] == [
        ("甲", "辰"), ("乙", "巳"), ("丙", "午")
    ]
    assert all(item.chart_provider == "sxtwl" for item in contexts)


def test_year_contexts_reject_reverse_range():
    with pytest.raises(ValueError, match="start_year"):
        year_contexts(chart(), 2026, 2024)


def test_dayun_policy_does_not_guess():
    with pytest.raises(NotImplementedError, match="顺逆"):
        DayunPolicy().calculate(chart())


def test_classical_approx_dayun_is_explicit_and_traceable():
    value = SxtwlBaziProvider().calculate(BirthInput(1990, 2, 1, 12, gender="男"))
    result = ClassicalApproxDayunPolicy().calculate(value)

    assert len(result) == 8
    assert result[0]["policy"] == "classical_approx_v2"
    assert result[0]["approximate"] is True
    # 1990-02-01 在立春前，年柱属己巳（阴年）；阴年男逆排，故为 backward
    assert result[0]["direction"] == "backward"


def test_classical_approx_dayun_requires_gender():
    with pytest.raises(ValueError, match="gender"):
        ClassicalApproxDayunPolicy().calculate(chart())


# ── 起运：数到相邻的「节」，不是数到下一个立春 ────────────────────────────


def test_start_age_counts_to_the_next_jie_when_forward():
    """庚午阳年男顺行：起运从出生时刻数到下一个节（小暑）。"""
    first = dayun(BirthInput(1990, 6, 15, 12, gender="男"))[0]

    assert first["direction"] == "forward"
    assert first["start_boundary"] == "小暑"
    assert first["start_offset_days"] == pytest.approx(22.209, abs=0.01)
    assert first["start_age_years"] == pytest.approx(7.40, abs=0.01)


def test_start_age_counts_to_the_previous_jie_when_backward():
    """庚午阳年女逆行：起运从出生时刻数到上一个节（芒种）。"""
    first = dayun(BirthInput(1990, 6, 15, 12, gender="女"))[0]

    assert first["direction"] == "backward"
    assert first["start_boundary"] == "芒种"
    assert first["start_offset_days"] == pytest.approx(9.218, abs=0.01)
    assert first["start_age_years"] == pytest.approx(3.07, abs=0.01)


def test_start_age_is_not_a_fixed_february_boundary():
    """回归：起运点曾硬编码成 2 月 4 日，把起运年龄算成几十岁。"""
    first = dayun(BirthInput(1990, 6, 15, 12, gender="男"))[0]

    assert first["start_age_years"] < 10


def test_start_age_parts_follow_three_days_one_year():
    assert start_age_parts(0.0) == (0, 0, 0)
    assert start_age_parts(3.0) == (1, 0, 0)
    assert start_age_parts(1.0) == (0, 4, 0)
    assert start_age_parts(0.25) == (0, 1, 0)


def test_start_age_parts_rejects_negative_offset():
    with pytest.raises(ValueError, match="不能为负"):
        start_age_parts(-0.1)


# ── 大运干支：从月柱起按六十甲子逐位推 ──────────────────────────────────


def test_dayun_pillars_step_one_position_in_sexagenary_order():
    """己巳阴年男逆行：月柱丁丑起，大运应为丙子、乙亥、甲戌……"""
    result = dayun(BirthInput(1990, 2, 1, 12, gender="男"))

    assert [(item["heavenly_stem"], item["earthly_branch"]) for item in result[:4]] == [
        ("丙", "子"), ("乙", "亥"), ("甲", "戌"), ("癸", "酉"),
    ]


def test_dayun_pillars_step_forward_for_yang_year_male():
    """庚午阳年男顺行：月柱壬午起，大运应为癸未、甲申、乙酉……"""
    result = dayun(BirthInput(1990, 6, 15, 12, gender="男"))

    assert [(item["heavenly_stem"], item["earthly_branch"]) for item in result[:3]] == [
        ("癸", "未"), ("甲", "申"), ("乙", "酉"),
    ]


def test_dayun_stems_do_not_repeat_across_sequences():
    """回归：递进量曾写成 ±10，使八步大运的天干完全不变。"""
    result = dayun(BirthInput(1990, 6, 15, 12, gender="男"))

    assert len({item["heavenly_stem"] for item in result}) == 8


def test_dayun_sequences_are_ten_years_apart():
    result = dayun(BirthInput(1990, 6, 15, 12, gender="男"))

    ages = [item["start_age_years"] for item in result]
    assert ages[1] - ages[0] == pytest.approx(10, abs=0.01)
    assert ages == sorted(ages)


# ── 流月：由「节」划界，一个干支年恰好十二个月 ───────────────────────────


def test_flow_months_covers_the_twelve_months_of_a_ganzhi_year():
    months = flow_months(1990)

    assert len(months) == 12
    assert months[0].jie_name == "立春"
    assert [item.earthly_branch for item in months] == list("寅卯辰巳午未申酉戌亥子丑")
    assert "".join(item.heavenly_stem for item in months) == "戊己庚辛壬癸甲乙丙丁戊己"
    # 小寒落在 1991-01-06，但干支年仍属庚午
    assert {item.ganzhi_year for item in months} == {1990}


def test_flow_months_are_contiguous_and_close_at_next_lichun():
    months = flow_months(1990)

    for earlier, later in pairwise(months):
        assert earlier.end == later.start
    assert months[-1].end == lichun_moment(1991)


def test_month_contexts_start_at_the_jie_moment_itself():
    """节时刻当刻即属于新的一月，边界不含糊。"""
    months = flow_months(1990)
    first = months[0]

    assert first.start == lichun_moment(1990)
    assert (first.heavenly_stem, first.earthly_branch) == ("戊", "寅")


def test_month_contexts_reject_reverse_range():
    with pytest.raises(ValueError, match="start"):
        month_contexts(datetime(2024, 6, 1), datetime(2024, 1, 1))


def test_month_contexts_reject_empty_range():
    with pytest.raises(ValueError, match="start"):
        month_contexts(datetime(2024, 6, 1), datetime(2024, 6, 1))
