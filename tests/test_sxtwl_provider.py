"""sxtwl provider 的真实库集成测试。"""

import pytest

from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from engines.bazi.golden import compare_chart


def pillars_of(chart):
    return [
        (pillar.heavenly_stem, pillar.earthly_branch) for pillar in chart.pillars
    ]


def test_sxtwl_returns_four_pillars_and_provenance():
    birth = BirthInput(1990, 2, 1, 12, longitude=116.4, latitude=39.9)
    chart = BaziCalculator(SxtwlBaziProvider()).calculate_chart(birth)

    assert [pillar.name for pillar in chart.pillars] == ["year", "month", "day", "hour"]
    assert chart.provider == "sxtwl"
    assert chart.algorithm_version == "sxtwl-2.0.7-bazi-v2"
    assert chart.day_master == chart.pillars[2].heavenly_stem
    assert chart.pillars[0].hidden_stems
    assert [pillar.ten_god for pillar in chart.pillars] == ["食神", "比肩", "日主", "劫财"]
    assert [pillar.na_yin for pillar in chart.pillars] == ["大林木", "涧下水", "山下火", "天河水"]


def test_sxtwl_handles_li_chun_year_boundary():
    before = BirthInput(2024, 2, 3, 12)
    after = BirthInput(2024, 2, 5, 12)
    provider = SxtwlBaziProvider()

    before_chart = provider.calculate(before)
    after_chart = provider.calculate(after)

    assert before_chart.pillars[0].earthly_branch != after_chart.pillars[0].earthly_branch


def test_true_solar_time_requires_longitude():
    provider = SxtwlBaziProvider(use_true_solar_time=True)

    try:
        provider.calculate(BirthInput(1990, 2, 1, 12))
    except ValueError as exc:
        assert "longitude" in str(exc)
    else:
        raise AssertionError("missing longitude should be rejected")


def test_true_solar_time_is_explicit_and_can_change_hour_boundary():
    birth = BirthInput(1990, 2, 1, 23, 50, longitude=121.5, latitude=31.2)
    civil = SxtwlBaziProvider(use_true_solar_time=False).calculate(birth)
    solar = SxtwlBaziProvider(use_true_solar_time=True).calculate(birth)

    assert civil.birth == solar.birth == birth
    assert compare_chart(civil, {"provider": "sxtwl"}) == []
    assert compare_chart(solar, {"provider": "sxtwl"}) == []


# ── 晚子时（23:00-24:00）：流派分歧必须显式化 ─────────────────────────────


def test_late_zi_default_keeps_day_pillar_and_borrows_next_day_hour_stem():
    """默认 no_roll：日柱仍属当日，时柱天干按次日日干推（sxtwl 口径）。"""
    provider = SxtwlBaziProvider()
    late = provider.calculate(BirthInput(1990, 6, 15, 23, 30))
    next_early = provider.calculate(BirthInput(1990, 6, 16, 0, 30))

    assert provider.late_zi_policy == "no_roll"
    assert pillars_of(late)[2] == ("辛", "亥")
    assert pillars_of(next_early)[2] == ("壬", "子")
    # 两个口径的时柱本来就相同，分歧只在日柱
    assert pillars_of(late)[3] == pillars_of(next_early)[3] == ("庚", "子")


def test_late_zi_roll_policy_moves_day_pillar_into_the_next_day():
    """roll：23:00 起日柱即进次日，时柱为次日子时（子时换日）。"""
    late = SxtwlBaziProvider(late_zi_policy="roll").calculate(
        BirthInput(1990, 6, 15, 23, 30)
    )

    assert pillars_of(late)[2] == ("壬", "子")
    assert pillars_of(late)[3] == ("庚", "子")


def test_late_zi_policy_is_recorded_in_algorithm_version():
    """非默认口径必须改版本号，否则同版本会掩盖不同结果。"""
    default = SxtwlBaziProvider().calculate(BirthInput(1990, 6, 15, 23, 30))
    rolled = SxtwlBaziProvider(late_zi_policy="roll").calculate(
        BirthInput(1990, 6, 15, 23, 30)
    )

    assert default.algorithm_version == "sxtwl-2.0.7-bazi-v2"
    assert rolled.algorithm_version == "sxtwl-2.0.7-bazi-v2+roll"


def test_late_zi_policy_does_not_touch_other_hours():
    birth = BirthInput(1990, 6, 15, 12, 0)

    assert pillars_of(SxtwlBaziProvider().calculate(birth)) == pillars_of(
        SxtwlBaziProvider(late_zi_policy="roll").calculate(birth)
    )


def test_late_zi_policy_rejects_unknown_value():
    with pytest.raises(ValueError, match="late_zi_policy"):
        SxtwlBaziProvider(late_zi_policy="guess")
