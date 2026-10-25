"""胎元、空亡、十二长生：三项无实质分歧的排盘派生量。

## 为什么单独一个模块

它们既不属于 provider（provider 只负责「把 sxtwl 的结果转成模型」），
也不属于事实层（事实是给规则当条件的；这三项目前没有任何断语在用它们
当条件，先做成命盘属性）。放在这里，由 provider 一次性算好挂到
``Chart.auxiliary``，前端与报告直接读，不必重算。

## 口径声明

- **胎元**：月干进一位、月支进三位。这是主流约定，但另有「月柱干支各进
  一位」等说法 —— ``policy`` 里写明采用哪一种，不静默。
- **空亡**：以日柱起旬，恒为两支。无分歧。
- **十二长生**：**只做阳干**。阳干顺行是共识（甲长生在亥、丙戊在寅、
  庚在巳、壬在申）；阴干有两说（阴干逆行 / 阴阳同生同死），本项目不做
  静默选择 —— 阴干返回 ``None``，并在 ``policy`` 里说明原因。
"""

from __future__ import annotations

from typing import Any

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

#: 阳干的长生起点：甲亥、丙戊寅、庚巳、壬申。
CHANGSHENG_START: dict[str, str] = {"甲": "亥", "丙": "寅", "戊": "寅", "庚": "巳", "壬": "申"}

#: 十二长生顺序（阳干顺行）。
TWELVE_STAGES: tuple[str, ...] = (
    "长生", "沐浴", "冠带", "临官", "帝旺", "衰",
    "病", "死", "墓", "绝", "胎", "养",
)

#: 旬空表：按日柱所在的旬（六十甲子每十个一旬）取两支。
KONG_WANG_BY_DECADE: tuple[tuple[str, str], ...] = (
    ("戌", "亥"),  # 甲子旬
    ("申", "酉"),  # 甲戌旬
    ("午", "未"),  # 甲申旬
    ("辰", "巳"),  # 甲午旬
    ("寅", "卯"),  # 甲辰旬
    ("子", "丑"),  # 甲寅旬
)

POLICY: dict[str, str] = {
    "tai_yuan": "month_stem_plus_1__month_branch_plus_3",
    "kong_wang": "decade_of_day_pillar",
    "twelve_stage": "yang_stems_only__forward",
    "note": (
        "胎元另有「月柱干支各进一位」等说法，此处取月干进一、月支进三；"
        "十二长生阴干有「逆行」与「阴阳同生同死」两说，本实现只给阳干，"
        "阴干留空而不静默选择。"
    ),
}


def _index(text: str, char: str) -> int:
    return text.index(char)


def tai_yuan(month_stem: str, month_branch: str) -> str:
    """胎元：月干进一位、月支进三位（十天干、十二地支各自循环）。"""
    stem = STEMS[(_index(STEMS, month_stem) + 1) % 10]
    branch = BRANCHES[(_index(BRANCHES, month_branch) + 3) % 12]
    return stem + branch


def kong_wang(day_stem: str, day_branch: str) -> tuple[str, str]:
    """日柱旬空：先求日柱在六十甲子中的序号，再按旬取两支。"""
    stem = _index(STEMS, day_stem)
    branch = _index(BRANCHES, day_branch)
    # 解同余：index ≡ stem (mod 10)，index ≡ branch (mod 12)，0 ≤ index < 60。
    index = next(i for i in range(60) if i % 10 == stem and i % 12 == branch)
    return KONG_WANG_BY_DECADE[index // 10]


def twelve_stage(day_stem: str, branch: str) -> str | None:
    """日主在某支的十二长生状态；阴干返回 ``None``（两说并存，不猜）。"""
    start = CHANGSHENG_START.get(day_stem)
    if start is None:
        return None
    offset = (_index(BRANCHES, branch) - _index(BRANCHES, start)) % 12
    return TWELVE_STAGES[offset]


def auxiliary_of(month_stem: str, month_branch: str, day_stem: str,
                 day_branch: str, branches: tuple[str, ...]) -> dict[str, Any]:
    """把三项算成一个字典，挂在 ``Chart.auxiliary`` 上。

    ``kong_wang_hit`` 是四支里落入空亡的柱名 —— 断语真正会用到的形态是
    「某柱空亡」，而不是「空亡是哪两支」。
    """
    empty = kong_wang(day_stem, day_branch)
    hits = [
        name for name, branch in zip(("year", "month", "day", "hour"), branches)
        if branch in empty
    ]
    return {
        "tai_yuan": tai_yuan(month_stem, month_branch),
        "kong_wang": list(empty),
        "kong_wang_hit": hits,
        "stages": {
            name: twelve_stage(day_stem, branch)
            for name, branch in zip(("year", "month", "day", "hour"), branches)
        },
        "policy": dict(POLICY),
    }
