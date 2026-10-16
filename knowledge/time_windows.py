"""事件窗口：把时间轴接上知识层，产出可回溯的信号而不是预测。

**这一层存在的理由。** 时间轴（:mod:`engines.bazi.time_engine`）只知道干支，
知识层（规则库）只知道本命盘。两者之间缺一层把「2028 年的流年干支」
翻成「对这张盘意味着什么」，而且翻的过程要能一步步追回去。

**它刻意不做的事。** 不做预测。输出形如
``2028年，信号：财星入命、冲太岁，证据强度0.48`` —— 报的是「这一年的结构
信号是什么、有多厚」，不是「你今年会发财」。区别不在措辞，在产出物本身：
这里没有一处会给出必然性判断，因为信号的定义就是「命盘里出现了什么结构」。

**信号与规则的关系（重要）。** 本轮的信号全部由
:mod:`knowledge.flow_facts` 的事实直接命名，**没有引入流年规则**。
原因不是懒，是见证纪律对不上：本命盘规则的见证是一张命盘，而流年规则的
见证是「命盘 + 年份」这一对，塞不进 ``RULE_WITNESS`` 的四元组。硬塞
会让见证独占性检查失去意义。所以这一轮先把事实层与命名做扎实，
规则化的流年断语留给下一轮，并已在报告里写明它需要先定见证口径。

主题过滤用的是显式声明的 :data:`TOPIC_TEN_GODS` —— 哪几个十神与哪个主题
相关，是一张可以复核的表，不是藏在代码里的判断。
"""

from __future__ import annotations

from dataclasses import dataclass

from engines.bazi.models import Chart
from engines.bazi.time_engine import (
    DayunPolicy,
    YearContext,
    year_context,
)
from knowledge.evidence import StrengthBreakdown, score_support
from knowledge.flow_facts import flow_facts
from knowledge.topics import resolve

#: 每个信号的基础置信度。流年与大运同值 —— 两条轴都是**确定性的干支推算**，
#: 差别在推算策略的近似程度，而那由 ``DayunPolicy`` 自己标注（``approximate``），
#: 不体现在置信度上。
SIGNAL_CONFIDENCE = 0.6

#: 十神 → 信号名。取传统的五分法（财 / 官 / 食伤 / 比劫 / 印），
#: 不按十个十神各起一个名 —— 「正财入命」与「偏财入命」在结构描述层面
#: 是同一类信号，拆开只会让报告变长而不增加信息。
GOD_SIGNAL = {
    "正财": "财星", "偏财": "财星",
    "正官": "官星", "七杀": "官星",
    "食神": "食伤", "伤官": "食伤",
    "比肩": "比劫", "劫财": "比劫",
    "正印": "印星", "偏印": "印星",
}

#: 主题 → 该主题关心的十神分组。显式声明，可复核。
TOPIC_TEN_GODS = {
    "wealth": ("财星",),
    "career": ("官星",),
    "marriage": ("官星", "财星"),
    "health": ("印星", "比劫"),
    "destiny": ("财星", "官星", "食伤", "比劫", "印星"),
    "structure": ("财星", "官星", "食伤", "比劫", "印星"),
}

AXIS_LABEL = {"liunian": "流年", "dayun": "大运"}


@dataclass(frozen=True)
class Signal:
    """一条结构信号。它描述「出现了什么」，不描述「会发生什么」。"""

    name: str
    axis: str
    kind: str
    detail: str
    source: str

    @property
    def label(self) -> str:
        return f"{AXIS_LABEL.get(self.axis, self.axis)}{self.name}"


@dataclass(frozen=True)
class TimeWindow:
    year: int
    topic: str
    topic_name: str
    liunian: YearContext
    dayun: dict[str, object] | None
    signals: tuple[Signal, ...]
    breakdown: StrengthBreakdown

    @property
    def strength(self) -> float:
        return self.breakdown.final

    def to_report(self) -> str:
        """输出一行人读的信号摘要。

        刻意不含任何「会」「一定」「必将」—— 这份报告的每个词都要能
        被信号本身支撑。没有信号的年份报「本年无显著结构信号」，
        不报「平稳无事」：后者是一句判断，前者是一个事实。
        """
        if not self.signals:
            return f"{self.year}年，无显著结构信号"
        names = "、".join(dict.fromkeys(signal.name for signal in self.signals))
        return f"{self.year}年，信号：{names}，证据强度{self.strength:.2f}"

    def to_dict(self) -> dict[str, object]:
        return {
            "year": self.year,
            "topic": self.topic,
            "topic_name": self.topic_name,
            "liunian": {
                "stem": self.liunian.heavenly_stem,
                "branch": self.liunian.earthly_branch,
                "provider": self.liunian.chart_provider,
            },
            "dayun": self.dayun,
            "signals": [
                {
                    "name": signal.name,
                    "label": signal.label,
                    "axis": signal.axis,
                    "kind": signal.kind,
                    "detail": signal.detail,
                    "source": signal.source,
                }
                for signal in self.signals
            ],
            "strength": self.strength,
            "strength_breakdown": self.breakdown.to_dict(),
            "report": self.to_report(),
        }


def _dayun_in_effect(
    dayun: tuple[dict[str, object], ...], age: int
) -> dict[str, object] | None:
    """返回 ``age`` 岁所处的那步大运；起运前返回 ``None``。

    ``start_age_years`` 是浮点（三日折一年算出来的），所以判据用
    ``start <= age < start + 10`` 而不是按整数起运年龄切 —— 后者会让
    恰好落在起运那一年的盘归错大运。
    """
    for entry in dayun:
        start = float(entry["start_age_years"])  # type: ignore[arg-type]
        if start <= age < start + 10:
            return entry
    return None


def _signals_for(chart: Chart, axis: str, stem: str, branch: str) -> tuple[Signal, ...]:
    grouped: dict[str, list[object]] = {}
    for fact in flow_facts(chart, axis, stem, branch):
        grouped.setdefault(fact.type, []).append(fact.value)

    signals: list[Signal] = []

    for god in grouped.get(f"{axis}_stem_ten_god", ()):
        name = GOD_SIGNAL.get(str(god), str(god))
        roots = grouped.get(f"{axis}_stem_ten_god_root", ())
        rooted = "有根" in roots
        signals.append(Signal(
            name=f"{name}入命",
            axis=axis,
            kind=f"{axis}_stem_ten_god",
            detail=(
                f"{AXIS_LABEL[axis]}天干{stem}对日主为{god}"
                f"，且四支藏干有同类（有根）" if rooted
                else f"{AXIS_LABEL[axis]}天干{stem}对日主为{god}，四支藏干无同类（虚透）"
            ),
            source=f"time.{axis}.heavenly_stem",
        ))

    for god in grouped.get(f"{axis}_branch_ten_god", ()):
        name = GOD_SIGNAL.get(str(god), str(god))
        signals.append(Signal(
            name=f"{name}坐{AXIS_LABEL[axis]}",
            axis=axis,
            kind=f"{axis}_branch_ten_god",
            detail=f"{AXIS_LABEL[axis]}地支{branch}本气对日主为{god}",
            source=f"time.{axis}.earthly_branch.hidden_stems",
        ))

    for pair in grouped.get(f"{axis}_relation_pairs", ()):
        # ``name`` 只放关系本身（如「六合酉」），轴名由 ``label`` 统一加。
        # 早先这里给大运的 name 加了「大运」前缀，而 label 又加一次，
        # 结果报出「大运大运六害酉」—— 两处都以为自己负责轴名。
        signals.append(Signal(
            name=str(pair).split("（")[0],
            axis=axis,
            kind=f"{axis}_relation_pairs",
            detail=f"{AXIS_LABEL[axis]}地支{branch}与命盘{pair}",
            source=f"time.{axis}.earthly_branch",
        ))

    return tuple(signals)


def analyze_period(
    chart: Chart,
    start_year: int,
    end_year: int,
    topic: str,
    *,
    dayun_policy: DayunPolicy | None = None,
) -> tuple[TimeWindow, ...]:
    """分析 ``[start_year, end_year]`` 内每一年的结构信号。

    ``topic`` 可以是别名（如「财运」），内部解析为规范主题 ID。
    ``dayun_policy`` 缺省时**不算大运**，只报流年 —— 大运需要流派选择
    （顺逆规则不同流派有分歧），不猜默认值。传 ``ClassicalApproxDayunPolicy()``
    即启用，且结果会带 ``approximate: True`` 标注。
    """
    if start_year > end_year:
        raise ValueError("start_year 不能大于 end_year。")

    resolved = resolve(topic)
    relevant = TOPIC_TEN_GODS.get(resolved.id, TOPIC_TEN_GODS["structure"])
    policy = dayun_policy or DayunPolicy()
    birth_year = chart.birth.year

    # 大运序列只跟命盘有关，与年份无关 —— 提到循环外算一次。
    # 未选流派时 ``name == "unspecified"``，此时不算大运而不是抛异常：
    # 「今年没有大运信息」是一个合法的部分结果，让整段分析失败反而不对。
    sequence = policy.calculate(chart) if policy.name != "unspecified" else ()

    windows: list[TimeWindow] = []
    for year in range(start_year, end_year + 1):
        context = year_context(chart, year)
        age = year - birth_year
        dayun = _dayun_in_effect(sequence, age) if sequence else None

        signals = list(_signals_for(chart, "liunian", context.heavenly_stem, context.earthly_branch))
        if dayun is not None:
            signals.extend(_signals_for(
                chart, "dayun", str(dayun["heavenly_stem"]), str(dayun["earthly_branch"])
            ))

        # 主题过滤只作用在**十神类**信号上；地支关系（冲太岁等）对所有主题
        # 都成立，按主题筛掉会让「今年冲太岁」这件事在财富主题下消失 ——
        # 而它跟问什么无关。
        kept = tuple(
            signal for signal in signals
            if signal.kind.endswith("relation_pairs")
            or any(group in signal.name for group in relevant)
        )
        windows.append(TimeWindow(
            year=year,
            topic=resolved.id,
            topic_name=resolved.name,
            liunian=context,
            dayun=dayun,
            signals=kept,
            breakdown=score_support(
                tuple(SIGNAL_CONFIDENCE for _ in kept), 0
            ),
        ))

    return tuple(windows)
