"""sxtwl provider 的真实库集成测试。"""

from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from engines.bazi.golden import compare_chart


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
