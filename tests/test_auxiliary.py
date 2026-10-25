"""胎元 / 空亡 / 十二长生（Phase 6.4）。

三项都是纯公式，但各有各的口径问题，测试要钉的是**口径**而不只是结果：

- 胎元：月干进一、月支进三。另有「月柱干支各进一位」等说法，所以
  ``policy`` 必须写明采用哪一种；
- 空亡：以日柱起旬，恒为两支。无分歧，但旬首算错一位会静默偏一支；
- 十二长生：**只做阳干**。阴干有「逆行」与「阴阳同生同死」两说，
  本实现返回 ``None`` 而不静默选择 —— 这条由测试钉住。
"""

from __future__ import annotations

import pytest

from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from engines.bazi.auxiliary import (
    POLICY,
    kong_wang,
    tai_yuan,
    twelve_stage,
)

CALCULATOR = BaziCalculator(SxtwlBaziProvider())


# ── 胎元 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("month_stem", "month_branch", "expected"),
    [
        ("戊", "寅", "己巳"),   # 戊→己，寅→巳（进三位）
        ("丙", "寅", "丁巳"),
        ("甲", "子", "乙卯"),   # 子→卯
        ("癸", "亥", "甲寅"),   # 癸→甲（天干循环回甲），亥→寅（地支循环）
    ],
)
def test_tai_yuan_advances_one_stem_and_three_branches(month_stem, month_branch, expected):
    assert tai_yuan(month_stem, month_branch) == expected


def test_tai_yuan_wraps_around_both_cycles():
    """天干到癸、地支到亥都要回绕，不能越界。"""
    assert tai_yuan("癸", "亥") == "甲寅"
    assert tai_yuan("壬", "戌") == "癸丑"


# ── 空亡 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("day_stem", "day_branch", "expected"),
    [
        ("甲", "子", ("戌", "亥")),   # 甲子旬
        ("癸", "酉", ("戌", "亥")),   # 同旬
        ("甲", "戌", ("申", "酉")),   # 甲戌旬
        ("甲", "申", ("午", "未")),   # 甲申旬
        ("甲", "午", ("辰", "巳")),   # 甲午旬
        ("甲", "辰", ("寅", "卯")),   # 甲辰旬
        ("甲", "寅", ("子", "丑")),   # 甲寅旬
        ("癸", "亥", ("子", "丑")),   # 甲寅旬末
    ],
)
def test_kong_wang_follows_the_decade(day_stem, day_branch, expected):
    assert kong_wang(day_stem, day_branch) == expected


def test_kong_wang_is_always_two_branches():
    """六十甲子每一天都必须给出恰好两支空亡 —— 少一支就是旬首算错了。"""
    stems = "甲乙丙丁戊己庚辛壬癸"
    branches = "子丑寅卯辰巳午未申酉戌亥"
    seen = set()
    for index in range(60):
        stem = stems[index % 10]
        branch = branches[index % 12]
        result = kong_wang(stem, branch)
        assert len(result) == 2
        assert set(result) <= set(branches)
        seen.add(result)
    # 六旬各一对，共六种
    assert len(seen) == 6


def test_every_day_pillar_maps_to_exactly_one_decade():
    """日柱 → 旬空 是纯函数：同一日柱必须恒得同一答案。"""
    assert kong_wang("甲", "子") == kong_wang("甲", "子")


# ── 十二长生 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stem", "branch", "expected"),
    [
        ("甲", "亥", "长生"),
        ("甲", "子", "沐浴"),
        ("甲", "寅", "临官"),
        ("甲", "卯", "帝旺"),
        ("甲", "午", "死"),
        ("丙", "寅", "长生"),
        ("戊", "寅", "长生"),   # 丙戊同长生于寅
        ("庚", "巳", "长生"),
        ("庚", "酉", "帝旺"),
        ("壬", "申", "长生"),
        ("壬", "子", "帝旺"),
    ],
)
def test_twelve_stage_for_yang_stems(stem, branch, expected):
    assert twelve_stage(stem, branch) == expected


@pytest.mark.parametrize("stem", ["乙", "丁", "己", "辛", "癸"])
def test_yin_stems_return_none_instead_of_guessing(stem):
    """阴干有两说（逆行 / 同生同死），返回 None 而不是静默选一个。"""
    assert twelve_stage(stem, "午") is None


def test_yang_stems_cover_all_twelve_stages():
    stages = [twelve_stage("甲", branch) for branch in "子丑寅卯辰巳午未申酉戌亥"]
    assert sorted(stages) == sorted([
        "长生", "沐浴", "冠带", "临官", "帝旺", "衰",
        "病", "死", "墓", "绝", "胎", "养",
    ])


# ── 挂到命盘上 ─────────────────────────────────────────────────────────


def test_chart_carries_auxiliary_and_declares_its_policy():
    chart = CALCULATOR.calculate_chart(BirthInput(1990, 2, 28, 0))
    payload = chart.to_dict()["auxiliary"]

    assert payload["tai_yuan"] == "己巳"
    assert payload["kong_wang"] == ["戌", "亥"]
    assert set(payload["stages"]) == {"year", "month", "day", "hour"}
    assert payload["policy"] == POLICY
    # 口径必须写清楚，不是藏在代码里
    assert "两说" in payload["policy"]["note"]


def test_kong_wang_hit_names_the_pillars_that_fall_into_it():
    """落空亡的柱名要能直接读出来 —— 断语用的是「某柱空亡」，不是两支。"""
    chart = CALCULATOR.calculate_chart(BirthInput(1990, 2, 28, 0))
    payload = chart.to_dict()["auxiliary"]

    branches = [pillar["earthly_branch"] for pillar in chart.to_dict()["pillars"]]
    expected = [
        name for name, branch in zip(("year", "month", "day", "hour"), branches)
        if branch in payload["kong_wang"]
    ]
    assert payload["kong_wang_hit"] == expected


def test_yin_day_master_leaves_stages_empty_but_keeps_the_shape():
    """阴日主（乙）的星运全为 null，但键仍在 —— 前端显示「—」而不是崩。"""
    chart = CALCULATOR.calculate_chart(BirthInput(1985, 6, 15, 10))
    payload = chart.to_dict()["auxiliary"]
    assert chart.day_master == "乙"
    assert set(payload["stages"].values()) == {None}
