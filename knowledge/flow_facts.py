"""时间轴事实：流年与大运对日主的十神、以及与四支的结构关系。

**为什么单独一个模块，而不是并进** :mod:`knowledge.facts`。那里的 :func:`extract_facts`
吃的是一个 :class:`~engines.bazi.models.Chart`，产出的是**本命盘**事实。流年与大运
不是命盘的柱，它们是「某个时间点上叠加到命盘上的一柱」—— 同一个人在不同年份
的流年十神不同，而本命盘的事实不变。把两者并进一个函数，就得给它加一个
「要不要算流年」的开关，而默认值取哪一边都是猜。

所以这里的函数多收一个参数：``stem`` / ``branch``，即那一柱的干支。
同一份代码服务流年与大运，只靠调用方给的轴名前缀区分。

**不做的事**：不判吉凶。「流年天干是偏财」是一个结构事实；「今年会发财」不是。
吉凶属于规则层的断语，不属于事实层 —— 这一条边界与本命盘事实层完全相同。
"""

from __future__ import annotations

from engines.bazi.models import Chart
from engines.bazi.sxtwl_provider import BRANCH_RELATIONS, HIDDEN_STEMS
from engines.bazi.ten_gods import ten_god
from knowledge.facts import Fact

#: 支持的两条时间轴。名字同时用作事实键前缀。
AXES = ("liunian", "dayun")


def flow_facts(chart: Chart, axis: str, stem: str, branch: str) -> tuple[Fact, ...]:
    """返回 ``axis`` 这一柱相对本命盘的结构事实。

    ``axis`` 必须是 :data:`AXES` 之一。传别的值不会抛异常，只会产出一堆
    没人读的事实键 —— 那种静默错误比抛异常更难查，所以在入口挡住。
    """
    if axis not in AXES:
        raise ValueError(f"axis 必须是 {AXES} 之一，收到 {axis!r}。")

    day_stem = chart.pillars[2].heavenly_stem
    natal_branches = tuple(pillar.earthly_branch for pillar in chart.pillars)

    facts: list[Fact] = [
        Fact(f"{axis}_pillar", stem + branch, f"time.{axis}"),
        Fact(f"{axis}_stem_ten_god", ten_god(day_stem, stem), f"time.{axis}.heavenly_stem"),
    ]

    # 支的十神取**本气**（藏干第一位）。取中气或余气是另一种流派口径，
    # 与本命盘的 ``month_branch_ten_god`` 保持一致，不另立一套。
    main_qi = HIDDEN_STEMS[branch][0]
    stem_god = ten_god(day_stem, stem)
    branch_god = ten_god(day_stem, main_qi)
    facts.append(Fact(
        f"{axis}_branch_ten_god",
        branch_god,
        f"time.{axis}.earthly_branch.hidden_stems",
    ))

    # 这一柱的天干十神在四支藏干里有没有同类。判定与本命盘
    # ``ten_god_with_root`` 完全同口径（只看藏干，不看天干），不另立标准。
    #
    # 没有这个键，流年层只能报「流年是财星」，报不出「立不立得住」——
    # 而虚透与有根是这套规则库里最常用的结构限定，缺了它断语就没法分层。
    hidden_gods = {
        ten_god(day_stem, hidden)
        for pillar in chart.pillars
        for hidden in pillar.hidden_stems
    }
    facts.append(Fact(
        f"{axis}_stem_ten_god_root",
        "有根" if stem_god in hidden_gods else "无根",
        "chart.pillars[*].hidden_stems",
    ))

    # 与四支的结构关系。**冲太岁**这类说法就落在这里 —— 它说的是流年支
    # 与命盘四支的关系，不是流年自己的属性。
    #
    # 分两个键是刻意的：``{axis}_relations`` 只存关系名，与本命盘
    # ``has_relation`` 同一口径，供规则匹配；``{axis}_relation_pairs`` 存
    # 「冲的是哪一支」。后者不能省 —— 「冲日支」和「冲年支」是实质不同的
    # 两件事，只报一个「六冲」就把这个区别抹掉了。
    for relation, pairs in BRANCH_RELATIONS.items():
        for name, natal in zip(("year", "month", "day", "hour"), natal_branches):
            if frozenset((branch, natal)) in pairs:
                facts.append(Fact(
                    f"{axis}_relations",
                    relation,
                    f"time.{axis}.earthly_branch",
                ))
                facts.append(Fact(
                    f"{axis}_relation_pairs",
                    f"{relation}{natal}（{name}支）",
                    f"time.{axis}.earthly_branch",
                ))

    return tuple(facts)
