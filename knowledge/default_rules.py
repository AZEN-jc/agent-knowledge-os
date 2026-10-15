"""默认规则库装配。

装配期做四件校验，都放在这里而不是靠人工自觉：

1. **流派校验**：每条规则的 ``school`` 必须是已注册流派，拼错即报错。
2. **主题校验**：每条规则的 ``topic`` 必须是已登记主题，拼错即报错 ——
   否则规则会挂着一个没人认识的主题，永远不被任何分析选中，而且不报错。
3. **条件键校验**：每条规则的条件键必须存在于 :data:`knowledge.facts.FACT_SCHEMA`。
   条件键写错不会抛异常，只会让规则永远匹配不上 —— 一条死规则比一条错规则
   更难发现，所以在装配期一次性挡住。
4. **引文回对底本**：``classical`` 规则的 ``exact_quote`` 必须在
   ``corpus/canonical/`` 的底本正文里逐字找得到。改一个字就装配失败。

规则库分两层：

- **结构层**（``structural``）：由 :mod:`knowledge.structural_rules` 生成，可由
  ``engines.bazi`` 的定义表执行验证。
- **典籍层**（``classical``）：由 ``corpus/canonical/*/atoms/*.json`` 加载，
  每条都带 URN 与逐字引文，见 :mod:`knowledge.rule_atoms`。

两层的装配顺序是固定的（结构层先、典籍层后），不依赖目录遍历顺序 ——
顺序会影响 ``RuleRegistry`` 的插入次序，进而影响任何「取第一条」的行为。
"""

from __future__ import annotations

from knowledge.corpus import Corpus, load_corpus
from knowledge.facts import FACT_SCHEMA
from knowledge.rule_atoms import LoadReport, load_atom_dir
from knowledge.rules import Rule, RuleRegistry
from knowledge.schools import SchoolRegistry, default_school_registry
from knowledge.structural_rules import structural_rules
from knowledge.topics import known_topic_ids


def classical_rules(
    corpus: Corpus | None = None,
    schools: SchoolRegistry | None = None,
) -> tuple[Rule, ...]:
    """加载 corpus 下全部规则原子。

    没有原子文件时返回空元组而不是报错 —— 「典籍层暂时为空」是一个合法状态
    （Phase 2/3/4 就是），不该让整个规则库装不起来。
    """
    active_corpus = corpus if corpus is not None else load_corpus()
    active_schools = schools if schools is not None else default_school_registry()
    rules: list[Rule] = []
    for directory in active_corpus.atom_dirs():
        report: LoadReport = load_atom_dir(
            directory / "atoms",
            active_corpus,
            schools=active_schools,
            known_topics=known_topic_ids(),
        )
        rules.extend(report.rules)
    return tuple(rules)


def build_registry(
    *,
    schools: SchoolRegistry | None = None,
    validate: bool = True,
    corpus: Corpus | None = None,
    include_classical: bool = True,
) -> RuleRegistry:
    """装配规则库；``validate=False`` 仅供构造非法库的测试使用。"""
    school_registry = schools if schools is not None else default_school_registry()
    registry = RuleRegistry()
    registry.add_many(structural_rules())
    if include_classical:
        registry.add_many(classical_rules(corpus, school_registry))
    if validate:
        registry.validate_schools(school_registry)
        registry.validate_topics(known_topic_ids())
        registry.validate_condition_keys(set(FACT_SCHEMA))
    return registry


def default_registry() -> RuleRegistry:
    return build_registry()


def structural_registry() -> RuleRegistry:
    """只有结构层的规则库。给「不关心典籍层」的测试用。"""
    return build_registry(include_classical=False)


def default_schools() -> SchoolRegistry:
    return default_school_registry()
