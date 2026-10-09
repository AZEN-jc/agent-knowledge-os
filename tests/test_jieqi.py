"""Phase 1：节气精确时刻与干支年月分界测试。

核心不变量：年柱在立春**时刻**切换，月柱在十二「节」的**时刻**切换，
而不是在节气当天的 00:00 切换。
"""

from datetime import date, datetime, timedelta

import pytest
import sxtwl

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.jieqi import (
    BEIJING,
    BRANCHES,
    JIE_TO_MONTH_BRANCH,
    STEMS,
    ganzhi_year,
    lichun_moment,
    month_branch,
    month_pillar,
    solar_terms,
    year_pillar,
)

PROVIDER = SxtwlBaziProvider()


def at(*parts: int) -> datetime:
    """按北京时间构造时刻。"""
    return datetime(*parts, tzinfo=BEIJING)


def birth_at(moment: datetime) -> BirthInput:
    """把绝对时刻转成北京时间下的 BirthInput（秒被截断，故用 ±1 分钟留余量）。"""
    local = moment.astimezone(BEIJING)
    return BirthInput(local.year, local.month, local.day, local.hour, local.minute)


def pillars_of(birth: BirthInput):
    chart = PROVIDER.calculate(birth)
    return tuple((pillar.heavenly_stem, pillar.earthly_branch) for pillar in chart.pillars)


def jie_terms_of(year: int):
    """某公历年内实际发生的十二个「节」（含跨年的小寒，去重后按时刻排序）。"""
    found = {}
    for span in (year - 1, year):
        for term in solar_terms(span):
            if term.name in JIE_TO_MONTH_BRANCH and term.moment.year == year:
                found[term.moment] = term
    return tuple(found[key] for key in sorted(found))


# ── 节气数据本身 ────────────────────────────────────────────────────────


def test_solar_terms_cover_one_ganzhi_year():
    terms = solar_terms(1990)

    # 立春(1990) 起、到立春(1991) 止：24 个节气 + 收尾的立春
    assert len(terms) == 25
    assert terms[0].name == "立春"
    assert terms[-1].name == "立春"
    assert terms[0].moment.year == 1990
    assert terms[-1].moment.year == 1991
    assert all(terms[index].moment < terms[index + 1].moment for index in range(len(terms) - 1))


def test_known_lichun_moments_are_minute_accurate():
    # 立春时刻取自 sxtwl（寿星天文历）；用两个不同年代核对，防止取错年份的立春
    assert lichun_moment(1990).strftime("%Y-%m-%d %H:%M") == "1990-02-04 10:14"
    assert lichun_moment(2024).strftime("%Y-%m-%d %H:%M") == "2024-02-04 16:26"


def test_jie_table_covers_all_twelve_month_branches():
    assert len(JIE_TO_MONTH_BRANCH) == 12
    assert set(JIE_TO_MONTH_BRANCH.values()) == set(BRANCHES)


@pytest.mark.parametrize("year", [1990, 2000, 2024])
def test_each_calendar_year_has_exactly_twelve_jie(year):
    assert len(jie_terms_of(year)) == 12


# ── 立春：年柱在时刻切换，不是日界 ──────────────────────────────────────


def test_year_pillar_switches_at_lichun_moment_not_midnight():
    lichun = lichun_moment(1990)

    before = pillars_of(birth_at(lichun - timedelta(minutes=1)))[0]
    after = pillars_of(birth_at(lichun + timedelta(minutes=1)))[0]

    assert before == ("己", "巳")   # 立春前仍属己巳年
    assert after == ("庚", "午")    # 立春后进入庚午年
    # 立春当天 00:00 仍在立春前 —— 旧实现（按日分界）在这里就已经换年了
    assert pillars_of(BirthInput(1990, 2, 4, 0, 0))[0] == ("己", "巳")
    assert pillars_of(BirthInput(1990, 2, 4, 9, 0))[0] == ("己", "巳")


def test_ganzhi_year_uses_lichun_boundary():
    assert ganzhi_year(lichun_moment(1990) - timedelta(days=1)) == 1989
    assert ganzhi_year(lichun_moment(1990)) == 1990
    assert ganzhi_year(lichun_moment(1990) + timedelta(days=1)) == 1990
    assert year_pillar(lichun_moment(1990) - timedelta(days=1)) == ("己", "巳")


# ── 十二节：月柱在节令时刻切换 ──────────────────────────────────────────


@pytest.mark.parametrize("year", [1990, 2000, 2024])
def test_every_jie_switches_month_branch_at_its_moment(year):
    for term in jie_terms_of(year):
        expected_after = JIE_TO_MONTH_BRANCH[term.name]
        expected_before = BRANCHES[(BRANCHES.index(expected_after) - 1) % 12]

        assert month_branch(term.moment - timedelta(minutes=1)) == expected_before, term.name
        assert month_branch(term.moment) == expected_after, term.name
        assert month_branch(term.moment + timedelta(minutes=1)) == expected_after, term.name

        # 月柱（含天干）也必须在同一时刻切换
        before_pillar = pillars_of(birth_at(term.moment - timedelta(minutes=1)))[1]
        after_pillar = pillars_of(birth_at(term.moment + timedelta(minutes=1)))[1]
        assert before_pillar[1] == expected_before, term.name
        assert after_pillar[1] == expected_after, term.name
        assert before_pillar != after_pillar, term.name


def test_mangzhong_moment_is_minute_accurate():
    # 1990 芒种 06-06 06:46
    assert month_branch(at(1990, 6, 6, 6, 45)) == "巳"
    assert month_branch(at(1990, 6, 6, 6, 47)) == "午"
    assert month_pillar(at(1990, 6, 6, 6, 45)) == ("辛", "巳")
    assert month_pillar(at(1990, 6, 6, 6, 47)) == ("壬", "午")


def test_month_stem_follows_five_tiger_rule_including_zi_and_chou():
    """五虎遁：甲己之年丙作首……子、丑两月绕回，必须对 12 取模。"""
    # 己巳年（1990 立春前）寅月起丙：寅丙、卯丁、辰戊、巳己、午庚、未辛、
    # 申壬、酉癸、戌甲、亥乙、子丙、丑丁
    assert month_pillar(at(1990, 2, 1, 12)) == ("丁", "丑")
    # 庚午年寅月起戊：……亥丁、子戊、丑己
    assert month_pillar(at(1990, 6, 15, 12)) == ("壬", "午")
    # 大雪 1990-12-07 17:14：亥月转子月，月干必须跟着绕回而不是错位
    assert month_pillar(at(1990, 12, 7, 17, 13)) == ("丁", "亥")
    assert month_pillar(at(1990, 12, 7, 17, 15)) == ("戊", "子")


def test_month_stem_cycles_across_all_twelve_months_of_one_ganzhi_year():
    """一个干支年（立春→次年立春）内，十二节对应的月干必须连续不错位。"""
    jie = [term for term in solar_terms(1990) if term.name in JIE_TO_MONTH_BRANCH][:12]
    pillars = [
        month_pillar(term.moment + timedelta(minutes=1))
        for term in jie
    ]

    assert jie[0].name == "立春"
    assert [item[1] for item in pillars] == list("寅卯辰巳午未申酉戌亥子丑")
    # 1990 立春起为庚午年，庚年寅月起戊
    assert "".join(item[0] for item in pillars) == "戊己庚辛壬癸甲乙丙丁戊己"


# ── 闰月不影响八字月柱（月柱只由节气决定）───────────────────────────────


def test_lunar_leap_month_does_not_change_month_pillar():
    """2020 闰四月（公历 5/23–6/20）：月柱只跟节气走，闰月边界不切换月柱。

    闰四月期间横跨芒种（2020-06-05 12:58），月支在节气处切换 —— 这正是
    「月柱由节气而非农历月决定」的证据。
    """
    # 闰月前 / 闰月第一天 / 闰月内芒种前
    assert month_branch(at(2020, 5, 22, 12)) == "巳"
    assert month_branch(at(2020, 5, 23, 12)) == "巳"
    assert month_branch(at(2020, 6, 4, 12)) == "巳"
    # 闰月内芒种后 / 闰月最后一天 / 闰月后
    assert month_branch(at(2020, 6, 6, 12)) == "午"
    assert month_branch(at(2020, 6, 20, 12)) == "午"
    assert month_branch(at(2020, 6, 21, 12)) == "午"


# ── 时区：节气按绝对时刻比较，不受出生地时区影响 ────────────────────────


def test_same_wall_clock_in_different_timezones_gets_different_year_pillar():
    """立春 1990-02-04 10:14（北京）。东京 10:14 早一小时，仍属己巳年。"""
    shanghai = pillars_of(BirthInput(1990, 2, 4, 10, 14))
    tokyo = pillars_of(BirthInput(1990, 2, 4, 10, 14, timezone="Asia/Tokyo"))

    assert shanghai[0] == ("庚", "午")   # 同一绝对时刻恰在立春
    assert shanghai[1] == ("戊", "寅")
    assert tokyo[0] == ("己", "巳")      # 换算成北京 09:14，仍在立春前
    assert tokyo[1] == ("丁", "丑")


# ── 差分测试：与 sxtwl 的按日分界实现逐日比对 ───────────────────────────


def _sxtwl_year_month(birth: BirthInput):
    day = sxtwl.fromSolar(birth.year, birth.month, birth.day)
    year_gz = day.getYearGZ()
    month_gz = day.getMonthGZ()
    return (
        (STEMS[int(year_gz.tg)], BRANCHES[int(year_gz.dz)]),
        (STEMS[int(month_gz.tg)], BRANCHES[int(month_gz.dz)]),
    )


@pytest.mark.parametrize("year", [1990, 2000, 2010, 2020])
def test_differential_against_sxtwl_date_boundary(year):
    """非节气日必须与 sxtwl 完全一致；差异只允许出现在节令当天。

    这条差分测试同时验证了干支年序号、五虎遁月干和节令归属三件事：
    365 天里只要有一天算错，五虎遁或干支年序号就必然暴露。
    """
    jie_dates = {term.moment.date() for term in jie_terms_of(year)}
    mismatches = []
    boundary_days = 0
    current = date(year, 1, 1)
    while current.year == year:
        birth = BirthInput(current.year, current.month, current.day, 12)
        ours = (pillars_of(birth)[0], pillars_of(birth)[1])
        theirs = _sxtwl_year_month(birth)
        if ours != theirs:
            if current in jie_dates:
                boundary_days += 1
            else:
                mismatches.append((current.isoformat(), ours, theirs))
        current += timedelta(days=1)

    assert mismatches == [], f"非节气日出现 {len(mismatches)} 处不一致"
    assert boundary_days > 0, "差分测试必须覆盖到节气日，否则没有验证到分界逻辑"
