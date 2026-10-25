"""地支合局与天干五合的定义表。

这些是**定义**，不是流派判断：三合、三会、五合的成员与所化五行由
干支体系唯一确定，任何流派都接受。因此与 :mod:`engines.bazi.ten_gods`
同级 —— 是定义表，不是某家的断法。

为什么不塞进 ``ten_gods.py``：那个模块管的是「单个天干/地支怎么归类」，
这里管的是「几个地支凑在一起成为什么」。两类问题混在一个文件里，
改一处要读另一处的上下文。
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import combinations

#: 三合局：三支齐备才算成局，所化为一个五行。
SAN_HE: dict[tuple[str, str, str], str] = {
    ("寅", "午", "戌"): "火",
    ("申", "子", "辰"): "水",
    ("亥", "卯", "未"): "木",
    ("巳", "酉", "丑"): "金",
}

#: 三会方局：三支齐备（同一方位）成局。
SAN_HUI: dict[tuple[str, str, str], str] = {
    ("寅", "卯", "辰"): "木",
    ("巳", "午", "未"): "火",
    ("申", "酉", "戌"): "金",
    ("亥", "子", "丑"): "水",
}

#: 天干五合。
STEM_COMBINATIONS: dict[tuple[str, str], str] = {
    ("甲", "己"): "土",
    ("乙", "庚"): "金",
    ("丙", "辛"): "水",
    ("丁", "壬"): "木",
    ("戊", "癸"): "火",
}

#: 月支 → 季节。三合局的分组口径：寅卯辰春、巳午未夏、申酉戌秋、亥子丑冬。
#:
#: **辰未戌丑同时是「四季月」**（土旺之月），所以另有 ``month_is_siji``。
#: 两个口径并存不是含糊：断语里「春生」与「四季月」说的是不同的范围，
#: 前者含辰，后者专指辰。把辰从春里拿掉，会让「春生」的断语在辰月失效。
SEASON_OF_BRANCH: dict[str, str] = {
    "寅": "春", "卯": "春", "辰": "春",
    "巳": "夏", "午": "夏", "未": "夏",
    "申": "秋", "酉": "秋", "戌": "秋",
    "亥": "冬", "子": "冬", "丑": "冬",
}

#: 四季月（土旺）：辰未戌丑。
SIJI_BRANCHES: tuple[str, ...] = ("辰", "未", "戌", "丑")


def formed_combinations(branches: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """四支里成局的组合，返回 ``(局名, 五行)`` 元组。

    局名形如 ``三合火局`` / ``三会金局``。同一组支可能既不是三合也不是
    三会；只看齐备的三支，半合不算成局（半合是另一个概念，断语里
    「半合」与「局」用法不同，不混）。
    """
    present = list(dict.fromkeys(branches))
    found: list[tuple[str, str]] = []
    for trio, element in SAN_HE.items():
        if set(trio) <= set(present):
            found.append((f"三合{element}局", element))
    for trio, element in SAN_HUI.items():
        if set(trio) <= set(present):
            found.append((f"三会{element}局", element))
    return tuple(found)


def combination_elements(branches: Iterable[str]) -> tuple[str, ...]:
    """四支成局所化的五行（去重，按出现顺序）。"""
    return tuple(dict.fromkeys(element for _, element in formed_combinations(branches)))


def stem_combinations(stems: Iterable[str]) -> tuple[str, ...]:
    """四干里的五合，返回形如 ``甲己合土`` 的字符串。"""
    present = list(dict.fromkeys(stems))
    found: list[str] = []
    for left, right in combinations(present, 2):
        pair = (left, right) if (left, right) in STEM_COMBINATIONS else (right, left)
        if pair in STEM_COMBINATIONS:
            found.append(f"{pair[0]}{pair[1]}合{STEM_COMBINATIONS[pair]}")
    return tuple(found)
