"""可追溯的命理规则模型与匹配器。

规则是候选解释，不是事实；匹配器只判断结构条件是否满足，不把规则结论
升级成确定性预测。每条规则都要求来源、流派和证据字段，便于后续审查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("规则必须有 id。")
        if not self.source.strip():
            raise ValueError(f"规则 {self.id} 必须有 source。")
        if not self.school.strip():
            raise ValueError(f"规则 {self.id} 必须有 school。")
        if self.confidence not in VALID_CONFIDENCE:
            raise ValueError(f"规则 {self.id} 的 confidence 非法：{self.confidence}")
        if not self.condition:
            raise ValueError(f"规则 {self.id} 必须有 condition。")


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

    def list(self, *, school: str = "", category: str = "") -> tuple[Rule, ...]:
        return tuple(
            rule for rule in self._rules.values()
            if (not school or rule.school == school)
            and (not category or rule.category == category)
        )

    def match(self, facts: dict[str, Any], *, school: str = "", category: str = "") -> tuple[RuleMatch, ...]:
        """返回条件全部满足的规则。

        ``facts`` 的每个值可以是标量，也可以是元组（同类型事实有多条时）。
        元组按「包含」判断，见 :func:`condition_holds`。
        """
        matches = []
        for rule in self.list(school=school, category=category):
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
        pairs = []
        for rule_id in selected:
            rule = self.get(rule_id)
            for conflict in rule.conflicts_with:
                if conflict in selected:
                    pairs.append(tuple(sorted((rule_id, conflict))))
        return tuple(sorted(set(pairs)))
