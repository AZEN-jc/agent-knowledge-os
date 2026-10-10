"""默认规则库装配。

装配期做两件校验，都放在这里而不是靠人工自觉：

1. **流派校验**：每条规则的 ``school`` 必须是已注册流派，拼错即报错。
2. **条件键校验**：每条规则的条件键必须存在于 :data:`knowledge.evidence.FACT_SCHEMA`。
   条件键写错不会抛异常，只会让规则永远匹配不上 —— 一条死规则比一条错规则
   更难发现，所以在装配期一次性挡住。

当前默认规则库全部是 ``structural`` 层级。典籍层（``classical``）一条都没有，
原因与后续动作见 :mod:`knowledge.classical_backlog`。
"""

from __future__ import annotations

from knowledge.evidence import FACT_SCHEMA
from knowledge.rules import RuleRegistry
from knowledge.schools import SchoolRegistry, default_school_registry
from knowledge.structural_rules import structural_rules


def build_registry(
    *,
    schools: SchoolRegistry | None = None,
    validate: bool = True,
) -> RuleRegistry:
    """装配规则库；``validate=False`` 仅供构造非法库的测试使用。"""
    school_registry = schools if schools is not None else default_school_registry()
    registry = RuleRegistry()
    registry.add_many(structural_rules())
    if validate:
        registry.validate_schools(school_registry)
        registry.validate_condition_keys(set(FACT_SCHEMA))
    return registry


def default_registry() -> RuleRegistry:
    return build_registry()


def default_schools() -> SchoolRegistry:
    return default_school_registry()
