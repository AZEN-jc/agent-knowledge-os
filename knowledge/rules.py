"""可追溯的命理规则模型与匹配器。

规则是候选解释，不是事实；匹配器只判断结构条件是否满足，不把规则结论
升级成确定性预测。每条规则都要求来源、流派和证据字段，便于后续审查。

来源治理见 :mod:`knowledge.provenance`。这里只落地一条硬守卫：一条
``classical`` 规则若想进入 ``ACTIVE``，必须带齐可核验的典籍引文。缺引文
的典籍规则可以存在，但只能停在 ``UNREVIEWED``，不允许进入生产引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from knowledge.provenance import Citation, ReviewStatus, SourceTier
from knowledge.schools import SchoolRegistry

VALID_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


def condition_holds(actual: Any, expected: Any) -> bool:
    """判断某个事实值是否满足规则条件。

    同一类型的事实可以有多条（一个命盘里常常同时存在六合与自刑），归并后
    以元组形式传入；此时按「包含」判断。标量仍按相等判断，保持既有调用方式。
    只把容器当成多值，字符串不在此列，避免 ``"六合" in "六合六冲"`` 这类误命中。
    """
    if isinstance(actual, (list, tuple, set, frozenset)):
        return expected in actual
    return actual == expected


@dataclass(frozen=True)
class Rule:
    id: str
    source: str
    school: str
    category: str
    condition: dict[str, Any]
    conclusion: str
    confidence: str = "LOW"
    conflicts_with: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    note: str = ""
    topic: str = "general"
    source_tier: SourceTier = SourceTier.STRUCTURAL
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    citation: Citation | None = None
    version: str = "1"
    conflict_slot: str = ""
    conflict_value: str = ""

    def __post_init__(self) -> None:
        # 先把枚举字段收敛成枚举成员。否则调用方传字符串 "ACTIVE" 时，
        # `is ReviewStatus.ACTIVE` 为假，引文守卫会被整条绕过。
        object.__setattr__(self, "source_tier", SourceTier(self.source_tier))
        object.__setattr__(self, "review_status", ReviewStatus(self.review_status))
        if not self.id.strip():
            raise ValueError("规则必须有 id。")
        if not self.source.strip():
            raise ValueError(f"规则 {self.id} 必须有 source。")
        if not self.school.strip():
            raise ValueError(f"规则 {self.id} 必须有 school。")
        if not self.category.strip():
            raise ValueError(f"规则 {self.id} 必须有 category。")
        if not self.topic.strip():
            raise ValueError(f"规则 {self.id} 必须有 topic。")
        if self.confidence not in VALID_CONFIDENCE:
            raise ValueError(f"规则 {self.id} 的 confidence 非法：{self.confidence}")
        if not self.condition:
            raise ValueError(f"规则 {self.id} 必须有 condition。")
        if any(not str(key).strip() for key in self.condition):
            raise ValueError(f"规则 {self.id} 的 condition 含空条件键。")
        if self.source_tier is SourceTier.CLASSICAL:
            self._guard_classical_citation()
        if self.review_status is ReviewStatus.DEPRECATED and not self.note.strip():
            raise ValueError(f"规则 {self.id} 已废弃，必须在 note 里写明废弃原因。")
        if bool(self.conflict_slot) != bool(self.conflict_value):
            raise ValueError(
                f"规则 {self.id} 的 conflict_slot 与 conflict_value 必须成对出现："
                f"只给槽不给值，无法判断两条规则是否真的给出不同结论。"
            )

    def _guard_classical_citation(self) -> None:
        """典籍断语进入 ACTIVE 前必须能指向可核验原文。

        这是整个规则库最重要的一条约束。没有它，「不编造命理规则」就只是
        一句写在文档里的口号：任何人都可以录一条听起来很像《滴天髓》的话，
        系统照样会把它当权威引用出去。
        """
        if self.review_status is not ReviewStatus.ACTIVE:
            return
        if self.citation is None:
            raise ValueError(
                f"规则 {self.id} 是典籍断语且已置为 ACTIVE，必须提供 citation"
                f"（典籍名 + 底本 + 原文 + 可核验地址）。"
            )
        if not self.citation.is_verifiable:
            raise ValueError(
                f"规则 {self.id} 的引文不可核验：需要逐字原文与可打开的出处地址，"
                f"当前 book={self.citation.book!r} edition={self.citation.edition!r} "
                f"original_text={'有' if self.citation.original_text.strip() else '缺'} "
                f"url={'有' if self.citation.url.strip() else '缺'}。"
            )

    @property
    def is_production_ready(self) -> bool:
        """能否进入面向用户的报告。"""
        return self.review_status is ReviewStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "source": self.source,
            "school": self.school,
            "category": self.category,
            "topic": self.topic,
            "condition": dict(self.condition),
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "source_tier": str(self.source_tier),
            "review_status": str(self.review_status),
            "conflicts_with": list(self.conflicts_with),
            "evidence_required": list(self.evidence_required),
            "citation": self.citation.to_dict() if self.citation else None,
            "conflict_slot": self.conflict_slot,
            "conflict_value": self.conflict_value,
            "note": self.note,
        }


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    matched_conditions: tuple[str, ...]
    missing_conditions: tuple[str, ...] = ()


@dataclass
class RuleRegistry:
    """规则注册表；重复 ID 或未知冲突引用都拒绝。"""

    _rules: dict[str, Rule] = field(default_factory=dict)

    def add(self, rule: Rule) -> None:
        if rule.id in self._rules:
            raise ValueError(f"规则 ID 已存在：{rule.id}")
        self._rules[rule.id] = rule
        unknown = [item for item in rule.conflicts_with if item not in self._rules]
        if unknown:
            del self._rules[rule.id]
            raise ValueError(f"规则 {rule.id} 引用了未知冲突规则：{', '.join(unknown)}")

    def add_many(self, rules: list[Rule] | tuple[Rule, ...]) -> None:
        for rule in rules:
            self.add(rule)

    def get(self, rule_id: str) -> Rule:
        try:
            return self._rules[rule_id]
        except KeyError as exc:
            raise KeyError(f"未知规则：{rule_id}") from exc

    def select(
        self,
        *,
        school: str = "",
        category: str = "",
        topic: str = "",
        confidence: str = "",
        review_status: ReviewStatus | str = "",
        source_tier: SourceTier | str = "",
    ) -> tuple[Rule, ...]:
        """按维度筛选规则；空字符串表示不限制。"""
        return tuple(
            rule for rule in self._rules.values()
            if (not school or rule.school == school)
            and (not category or rule.category == category)
            and (not topic or rule.topic == topic)
            and (not confidence or rule.confidence == confidence)
            and (not review_status or str(rule.review_status) == str(review_status))
            and (not source_tier or str(rule.source_tier) == str(source_tier))
        )

    def production_ready(self) -> tuple[Rule, ...]:
        """可进入面向用户报告的规则（``review_status`` 为 ACTIVE）。"""
        return tuple(rule for rule in self._rules.values() if rule.is_production_ready)

    def match(
        self,
        facts: dict[str, Any],
        *,
        school: str = "",
        category: str = "",
        topic: str = "",
        production_only: bool = False,
    ) -> tuple[RuleMatch, ...]:
        """返回条件全部满足的规则。

        ``facts`` 的每个值可以是标量，也可以是元组（同类型事实有多条时）。
        元组按「包含」判断，见 :func:`condition_holds`。

        ``production_only`` 打开后只匹配 ACTIVE 规则；默认关闭，便于内部
        测试与演示覆盖尚未校核的规则。
        """
        matches = []
        for rule in self.select(school=school, category=category, topic=topic):
            if production_only and not rule.is_production_ready:
                continue
            matched = tuple(
                key for key, expected in rule.condition.items()
                if condition_holds(facts.get(key), expected)
            )
            missing = tuple(key for key in rule.condition if key not in matched)
            if not missing:
                matches.append(RuleMatch(rule=rule, matched_conditions=matched))
        return tuple(matches)

    def conflicts(self, rule_ids: list[str] | tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        selected = set(rule_ids)
        pairs: list[tuple[str, str]] = []
        for rule_id in selected:
            rule = self.get(rule_id)
            for conflict in rule.conflicts_with:
                if conflict in selected:
                    pairs.append(
                        (rule_id, conflict) if rule_id < conflict else (conflict, rule_id)
                    )
        return tuple(sorted(set(pairs)))

    def slot_conflicts(
        self, matches: tuple[RuleMatch, ...]
    ) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
        """按「结论槽」检测**真实**冲突，返回（规则对, 人类可读说明）。

        ``conflicts_with`` 只能表达静态的「这两条规则可能对不上」。但同一槽位
        上两条规则常常给出**相同**结论 —— 月支本气是正官、藏干透出的也是正官，
        两法一致，此时报冲突就是误报。所以这里再按槽分组，只有同槽且**取值
        不同**才算真冲突。分歧只在两法真的分道扬镳时才被抬出来。
        """
        slots: dict[str, list[Rule]] = {}
        for match in matches:
            if match.rule.conflict_slot:
                slots.setdefault(match.rule.conflict_slot, []).append(match.rule)
        pairs: set[tuple[str, str]] = set()
        notes: list[str] = []
        for slot, rules in slots.items():
            values = {rule.conflict_value for rule in rules}
            if len(values) < 2:
                continue
            ordered = sorted(rules, key=lambda rule: rule.id)
            for left in range(len(ordered)):
                for right in range(left + 1, len(ordered)):
                    first, second = ordered[left], ordered[right]
                    if first.conflict_value == second.conflict_value:
                        continue
                    pairs.add(
                        (first.id, second.id) if first.id < second.id else (second.id, first.id)
                    )
            notes.append(
                f"{slot} 出现分歧：{' / '.join(sorted(values))}；"
                f"涉及规则 {'、'.join(rule.id for rule in ordered)}。"
            )
        return tuple(sorted(pairs)), tuple(notes)

    def condition_keys(self) -> frozenset[str]:
        """规则库里出现过的全部条件键，用于校验它们都在事实词表内。"""
        return frozenset(key for rule in self._rules.values() for key in rule.condition)

    def validate_condition_keys(self, allowed: frozenset[str] | set[str]) -> None:
        """拒绝条件键拼错的规则。

        条件键写错不会报错，只会让规则永远匹配不上 —— 一条死规则比一条
        错规则更难发现，所以在这里一次性挡住。
        """
        unknown = sorted(self.condition_keys() - set(allowed))
        if unknown:
            raise ValueError(f"规则库引用了事实词表里不存在的条件键：{'、'.join(unknown)}")

    def validate_schools(self, school_registry: SchoolRegistry) -> None:
        """拒绝挂到未注册流派上的规则。"""
        for rule in self._rules.values():
            school_registry.require(rule.school)

    def stats(self) -> dict[str, Any]:
        rules = tuple(self._rules.values())
        return {
            "total": len(rules),
            "production_ready": len(self.production_ready()),
            "by_review_status": _count(rules, lambda r: str(r.review_status)),
            "by_source_tier": _count(rules, lambda r: str(r.source_tier)),
            "by_school": _count(rules, lambda r: r.school),
            "by_category": _count(rules, lambda r: r.category),
            "by_topic": _count(rules, lambda r: r.topic),
            "by_confidence": _count(rules, lambda r: r.confidence),
            "conflict_slots": len({rule.conflict_slot for rule in rules if rule.conflict_slot}),
            "static_conflict_pairs": len(_conflict_pairs(rules)),
        }

    def to_dicts(self, **filters: Any) -> list[dict[str, Any]]:
        return [rule.to_dict() for rule in self.select(**filters)]


def _count(rules: tuple[Rule, ...], key: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for rule in rules:
        name = str(key(rule))
        result[name] = result.get(name, 0) + 1
    return dict(sorted(result.items()))


def _conflict_pairs(rules: tuple[Rule, ...]) -> set[tuple[str, str]]:
    ids = {rule.id for rule in rules}
    pairs: set[tuple[str, str]] = set()
    for rule in rules:
        for conflict in rule.conflicts_with:
            if conflict in ids:
                pairs.add(
                    (rule.id, conflict) if rule.id < conflict else (conflict, rule.id)
                )
    return pairs


def with_status(rule: Rule, status: ReviewStatus) -> Rule:
    """返回同一规则、指定校核状态的副本。

    校验逻辑写在 ``__post_init__`` 里，所以从 ``UNREVIEWED`` 升到 ``ACTIVE``
    这一步同样会被引文守卫拦下 —— 不可能绕过构造期检查把未核校的典籍规则
    悄悄激活。
    """
    return replace(rule, review_status=status)
