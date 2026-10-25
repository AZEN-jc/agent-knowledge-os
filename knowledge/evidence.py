"""从确定性命盘构建可追溯证据（Evidence Layer）。

这一层是整个项目的核心创新点：**不让模型直接输出结论**。流程固定为

    命盘 → 事实提取 → 规则匹配 → 证据链 → 结论（带证据强度）

三条设计约束：

1. **事实只描述命盘里有什么**，不做吉凶判断。提取逻辑见 :mod:`knowledge.facts`。
2. **证据链必须能走回命盘要素**。每条命中的规则都带条件追踪（哪个条件、
   命盘实际取值、来自哪个要素），见 :class:`~knowledge.rules.ConditionTrace`。
   走不回去的引用会在 :attr:`Evidence.untraced_rule_ids` 里暴露出来。
3. **主题覆盖如实报告**。基础层（结构事实）与主题层（断语规则）分开统计，
   主题层为空时明说，不用结构事实冒充主题结论。见 :mod:`knowledge.topics`。

关于「证据强度」：它是**证据等级，不是事件发生概率**。算式见
:func:`score_strength`，并完整暴露在 :class:`StrengthBreakdown` 里供审计。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.bazi.models import Chart
from knowledge.facts import Fact, extract_facts
from knowledge.rules import RuleMatch, RuleRegistry
from knowledge.topics import STRUCTURAL_TOPIC, TopicStatus, resolve, status_for

CONFIDENCE_SCORES = {"LOW": 0.4, "MEDIUM": 0.7, "HIGH": 1.0}
"""置信等级到支持量的映射。支持量表示证据等级，不是事件发生概率。"""

SATURATION_K = 3.0
"""饱和常数。本实现选定的标度，不是典籍规定，也不是概率刻度。

作用是把「支持量」压进 (0, 1) 开区间：K 越大，需要越多规则命中才能达到同等强度。
"""

CONFLICT_PENALTY = 0.15
"""每处规则冲突对证据强度的扣减。"""


@dataclass(frozen=True)
class StrengthBreakdown:
    """证据强度的完整算式，逐项可核对。

    暴露算式而不只给一个数字，是为了让「为什么是 0.62」有答案 ——
    只给分数的强度模型，用户除了相信没有别的选择。
    """

    supporting_rules: int
    raw_support: float
    saturation_k: float
    after_saturation: float
    conflicts: int
    conflict_penalty: float
    final: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "supporting_rules": self.supporting_rules,
            "raw_support": self.raw_support,
            "saturation_k": self.saturation_k,
            "after_saturation": self.after_saturation,
            "conflicts": self.conflicts,
            "conflict_penalty": self.conflict_penalty,
            "final": self.final,
        }


def score_support(support: tuple[float, ...], conflicts: int) -> StrengthBreakdown:
    """强度公式的内核：按「支持量凹饱和 − 冲突扣减」打分。

    提出来是为了让时间轴层（:mod:`knowledge.time_windows`）复用**同一个**算式。
    那一层没有 ``RuleMatch`` 可传，但它有一批同样带置信度的信号；
    如果在那里另写一遍 ``raw / (raw + K)``，两个层的强度数字就再也不能比较 ——
    而这正是用户最需要能比较的地方（「本命局 0.62，2028 年 0.48」）。

    为什么不用「置信度均值」：均值完全不看命中条数 —— 命中 3 条和命中 20 条
    会得到同一个分数，而这两者的证据厚度显然不同。

    凹饱和函数 ``raw / (raw + K)`` 的性质：对条数单调递增、边际递减、
    且**永远到不了 1.0**。最后一点是刻意的：结构层证据再厚，也只是「命盘里
    有什么」，不该被读成「结论几乎确定」。
    """
    raw = sum(support)
    after = raw / (raw + SATURATION_K) if raw else 0.0
    penalty = CONFLICT_PENALTY * conflicts
    return StrengthBreakdown(
        supporting_rules=len(support),
        raw_support=round(raw, 4),
        saturation_k=SATURATION_K,
        after_saturation=round(after, 4),
        conflicts=conflicts,
        conflict_penalty=round(penalty, 4),
        final=round(max(0.0, min(1.0, after - penalty)), 4),
    )


def score_strength(
    matches: tuple[RuleMatch, ...], conflicts: tuple[tuple[str, str], ...]
) -> StrengthBreakdown:
    """规则命中版的强度计算；内核见 :func:`score_support`。"""
    return score_support(
        tuple(CONFIDENCE_SCORES[match.rule.confidence] for match in matches),
        len(conflicts),
    )


@dataclass(frozen=True)
class Evidence:
    topic: str
    """调用方传入的原始主题（可能是别名，如「事业」）。"""

    topic_id: str
    """解析后的规范主题 ID（如 ``career``）。"""

    topic_name: str
    status: TopicStatus
    coverage_note: str
    schools: tuple[str, ...]
    facts: tuple[Fact, ...]
    matches: tuple[RuleMatch, ...]
    conflicts: tuple[tuple[str, str], ...]
    strength: float
    strength_breakdown: StrengthBreakdown
    conflict_notes: tuple[str, ...] = ()

    @property
    def base_matches(self) -> tuple[RuleMatch, ...]:
        """公共结构层命中。所有主题共享。"""
        return tuple(match for match in self.matches if match.rule.topic == STRUCTURAL_TOPIC)

    @property
    def domain_matches(self) -> tuple[RuleMatch, ...]:
        """属于所请求主题的规则命中。

        问「公共结构层」时主题层与基础层重合 —— 那正是这个主题的含义。
        两者的判定口径必须一致：``build_evidence`` 也是按 ``rule.topic == 主题``
        划主题层，若这里改成「排除基础层」，同一个字段在同一个主题上会给出
        两个答案。
        """
        if self.topic_id == STRUCTURAL_TOPIC:
            return self.base_matches
        return tuple(
            match for match in self.matches if match.rule.topic == self.topic_id
        )

    @property
    def unreviewed_rule_ids(self) -> tuple[str, ...]:
        """命中的规则里尚未通过校核的那些。

        生产报告必须能一眼看出「这个结论里有多少依据还没核过」，
        否则未校核规则会被当成和已校核规则同等权威的东西展示出去。
        """
        return tuple(
            match.rule.id for match in self.matches if not match.rule.is_production_ready
        )

    @property
    def untraced_rule_ids(self) -> tuple[str, ...]:
        """命中了、但条件追踪断链的规则。

        正常情况下恒为空。它的价值是防止「证据链」退化成一句口号：
        只要有人绕过 ``RuleRegistry.match`` 手工拼一个没有来源的 RuleMatch，
        这里立刻暴露出来。
        """
        return tuple(match.rule.id for match in self.matches if not match.is_fully_traced)

    @property
    def is_fully_traced(self) -> bool:
        return not self.untraced_rule_ids

    def to_dict(self) -> dict[str, Any]:
        # 整段证据的人话总述（Phase 6.1）：先说覆盖状态，再说命中多少条、
        # 其中几条有典籍原文。读者先看这一句，再看逐条。
        from knowledge.explain import explain_evidence

        return {
            "topic": self.topic,
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "status": str(self.status),
            "coverage_note": self.coverage_note,
            "plain_summary": explain_evidence(self),
            "schools": list(self.schools),
            "facts": [
                {
                    "type": fact.type,
                    "value": fact.value,
                    "source": fact.source,
                    "confidence": fact.confidence,
                }
                for fact in self.facts
            ],
            # ── 证据链：结论 → 规则 → 条件 → 命盘要素 ──────────────────
            "chain": [match.to_dict() for match in self.matches],
            # ── 以下为兼容既有调用方的扁平视图 ────────────────────────
            "rules": [match.rule.id for match in self.matches],
            "sources": [match.rule.source for match in self.matches],
            "rule_provenance": [
                {
                    "id": match.rule.id,
                    "school": match.rule.school,
                    "source_tier": str(match.rule.source_tier),
                    "review_status": str(match.rule.review_status),
                    "confidence": match.rule.confidence,
                }
                for match in self.matches
            ],
            "base_rules": [match.rule.id for match in self.base_matches],
            "domain_rules": [match.rule.id for match in self.domain_matches],
            "unreviewed_rules": list(self.unreviewed_rule_ids),
            "untraced_rules": list(self.untraced_rule_ids),
            "conflicts": [list(pair) for pair in self.conflicts],
            "conflict_notes": list(self.conflict_notes),
            "strength": self.strength,
            "strength_breakdown": self.strength_breakdown.to_dict(),
        }


def build_evidence(
    chart: Chart,
    registry: RuleRegistry,
    topic: str = STRUCTURAL_TOPIC,
    *,
    production_only: bool = False,
) -> Evidence:
    """构建一份带证据链与主题覆盖说明的证据。

    匹配在**全量规则**上进行，再按 ``rule.topic`` 拆成基础层与主题层。
    不能把 ``topic`` 直接传给 ``match()`` 做过滤：那样问「事业」会命中 0 条
    规则，用户连命盘的结构事实都看不到；而只返回基础层又会把结构事实
    冒充成事业结论。两层并列、覆盖状态如实报告，才是诚实的做法。
    """
    facts = extract_facts(chart)
    matches = registry.match(facts, production_only=production_only)
    resolved = resolve(topic)
    selected = tuple(
        match
        for match in matches
        if match.rule.topic in {STRUCTURAL_TOPIC, resolved.id}
    )
    domain = tuple(match for match in selected if match.rule.topic == resolved.id)

    rule_ids = [match.rule.id for match in selected]
    # 冲突有两个来源：规则自己声明的静态对，以及同一结论槽上的真实分歧。
    slot_pairs, slot_notes = registry.slot_conflicts(selected)
    conflicts = tuple(sorted(set(registry.conflicts(rule_ids)) | set(slot_pairs)))

    breakdown = score_strength(selected, conflicts)
    status = status_for(resolved, len(domain))
    return Evidence(
        topic=topic,
        topic_id=resolved.id,
        topic_name=resolved.name,
        status=status,
        coverage_note=_coverage_note(resolved.name, status, resolved.blocked_by),
        schools=tuple(sorted({match.rule.school for match in selected})),
        facts=facts,
        matches=selected,
        conflicts=conflicts,
        strength=breakdown.final,
        strength_breakdown=breakdown,
        conflict_notes=slot_notes,
    )


def _coverage_note(name: str, status: TopicStatus, blocked_by: str) -> str:
    if status is TopicStatus.COVERED:
        return f"「{name}」主题有专属规则命中。"
    if status is TopicStatus.BASE_ONLY:
        return (
            f"「{name}」主题尚无断语规则：{blocked_by}"
            "以下仅为公共结构层证据，说明命盘里有什么，不构成对该主题的判断。"
        )
    return (
        f"「{name}」不是已登记的主题，没有对应的规则层。"
        "以下仅为公共结构层证据，不构成对该主题的判断。"
    )
