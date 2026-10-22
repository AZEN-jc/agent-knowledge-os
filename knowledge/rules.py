"""可追溯的命理规则模型与匹配器。

规则是候选解释，不是事实；匹配器只判断结构条件是否满足，不把规则结论
升级成确定性预测。每条规则都要求来源、流派和证据字段，便于后续审查。

来源治理见 :mod:`knowledge.provenance`。这里只落地一条硬守卫：一条
``classical`` 规则若想进入 ``ACTIVE``，必须带齐可核验的典籍引文。缺引文
的典籍规则可以存在，但只能停在 ``UNREVIEWED``，不允许进入生产引用。

匹配结果带**条件追踪**（:class:`ConditionTrace`）：每条条件不只记录「成立了」，
还记录「命盘给出的实际取值是什么、来自哪个命盘要素」。这是证据链能追溯到
用户面前的关键一跳 —— 只写「规则 R 命中」的匹配器，和黑盒没有区别。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from knowledge.facts import Fact, group_facts, index_facts
from knowledge.provenance import Citation, ReviewStatus, SourceTier
from knowledge.schools import SchoolRegistry

VALID_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}

VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")
"""规则版本号的形态：``1`` / ``2`` / ``1.3``。

**为什么版本号要收口。** ``version`` 之前是裸的 ``str = "1"``，什么都不校验：
空串、``"v2 final"``、``"第二版"`` 都能过。而版本号会被写进证据链与报告 ——
「这份报告用的是哪一版规则」是事后复核的唯一抓手。格式不收口，就没法按版本
比对两次分析的差异，也没法在升级时判断「这条规则改没改」。
"""

VALID_POLARITY = {"positive", "negative", "neutral"}
"""断语的倾向。

不是「吉凶预测」，而是**原文明说了方向**时的一个标签。典籍断语常直接写
「大贵」「主刑死」「平常」—— 不把这个方向带下去，语言层就可能把一条
凶断语转述成中性甚至正面的话。``neutral`` 是默认值，表示原文没有明确方向。
"""


def condition_holds(actual: Any, expected: Any) -> bool:
    """判断某个事实值是否满足规则条件。

    同一类型的事实可以有多条（一个命盘里常常同时存在六合与自刑），归并后
    以元组形式传入；此时按「包含」判断。标量仍按相等判断，保持既有调用方式。
    只把容器当成多值，字符串不在此列，避免 ``"六合" in "六合六冲"`` 这类误命中。

    **期望值也可以是容器**，含义与上面对称 —— 实际值是否在其中：

        {"month_branch": ["寅", "午", "戌"]}   # 月支是这三者之一

    没有这个写法，「寅午戌月俱吉」就得拆成三条规则。三条规则会各自命中、
    各自出一段结论，读者看到的是同一句话重复三遍，而不是一个集合；
    更要紧的是第三条一旦漏录，集合就少一块而不报错。

    **两边都是容器时按「有交集」判断**（Phase 3.3 修正）。此前第一分支先命中，
    于是 ``condition_holds(("六合", "六冲"), ["六合", "六冲"])`` 变成
    「这个列表是不是元组里的一个元素」→ ``False``。而这条规则的语义明明是
    「命盘有这两类关系中的任意一种」，命盘恰好两类都有时反而不命中 ——
    静默失效，不报错、不告警，只是少了一条结论。
    """
    actual_is_many = isinstance(actual, (list, tuple, set, frozenset))
    expected_is_many = isinstance(expected, (list, tuple, set, frozenset))
    if actual_is_many and expected_is_many:
        # 两侧都是集合语义：只要有一项对得上即成立。
        return bool(set(actual) & set(expected))
    if actual_is_many:
        return expected in actual
    if expected_is_many:
        return actual in expected
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
    polarity: str = "neutral"
    keywords: tuple[str, ...] = ()

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
        if self.polarity not in VALID_POLARITY:
            raise ValueError(f"规则 {self.id} 的 polarity 非法：{self.polarity}")
        if any(not str(word).strip() for word in self.keywords):
            raise ValueError(f"规则 {self.id} 的 keywords 含空串。")
        if not VERSION_PATTERN.match(self.version):
            raise ValueError(
                f"规则 {self.id} 的 version 非法：{self.version!r}。"
                "只接受非空的数字或点分数字（如 1 / 2 / 1.3）—— 版本号会被写进"
                "证据链与报告，格式不收口就无法按版本比对两次分析的差异。"
            )
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

    @property
    def urn(self) -> str:
        """规范标识；结构层规则没有，返回空串。"""
        return self.citation.urn if self.citation else ""

    def _guard_classical_citation(self) -> None:
        """典籍断语进入 ACTIVE 前必须能指向可核验原文。

        这是整个规则库最重要的一条约束。没有它，「不编造命理规则」就只是
        一句写在文档里的口号：任何人都可以录一条听起来很像《滴天髓》的话，
        系统照样会把它当权威引用出去。

        要求分三层，缺一层都不够：

        1. **有引文对象** —— 不然连书名都没有。
        2. **引文可核验** —— 逐字原文 + 可打开的地址。没有原文就无法判断
           引用有没有走样；没有地址就无从复核是不是转抄自二手断语。
        3. **引文带规范标识（URN）** —— 前两层只说明「有这么一段话」，
           说明不了「是哪一版、哪一卷、哪一条」。而版本恰恰是断语会打架的地方
           （「甲戊庚牛羊」与「甲戊兼牛羊」）。
        """
        if self.review_status is not ReviewStatus.ACTIVE:
            return
        if self.citation is None:
            raise ValueError(
                f"规则 {self.id} 是典籍断语且已置为 ACTIVE，必须提供 citation"
                f"（典籍名 + 底本 + 原文 + 可核验地址 + 规范标识 URN）。"
            )
        if not self.citation.is_verifiable:
            raise ValueError(
                f"规则 {self.id} 的引文不可核验：需要逐字原文与可打开的出处地址，"
                f"当前 book={self.citation.book!r} edition={self.citation.edition!r} "
                f"original_text={'有' if self.citation.original_text.strip() else '缺'} "
                f"url={'有' if self.citation.url.strip() else '缺'}。"
            )
        if not self.citation.is_canonical:
            raise ValueError(
                f"规则 {self.id} 的引文缺少规范标识 URN："
                "只有书名和地址，无法说明是哪一版、哪一卷、哪一条。"
                "同一部典籍不同底本的条文会打架，URN 是区分它们的唯一手段。"
                f"当前 urn={self.citation.urn!r}。"
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
            "polarity": self.polarity,
            "keywords": list(self.keywords),
            "source_tier": str(self.source_tier),
            "review_status": str(self.review_status),
            "conflicts_with": list(self.conflicts_with),
            "evidence_required": list(self.evidence_required),
            "citation": self.citation.to_dict() if self.citation else None,
            "urn": self.urn or None,
            "conflict_slot": self.conflict_slot,
            "conflict_value": self.conflict_value,
            "note": self.note,
        }


@dataclass(frozen=True)
class ConditionTrace:
    """一条条件被满足的完整依据。

    ``sources`` 是这条事实在命盘里的出处（形如 ``chart.pillars.month``），
    证据链靠它从「规则要求正官」走回「正官来自月支藏干」。
    """

    key: str
    expected: Any
    actual: Any
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "expected": self.expected,
            "actual": self.actual,
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class RuleMatch:
    """一条命中的规则，连同它的条件追踪。

    只保留 ``traces`` 一个真字段：``matched_conditions`` 由它派生。
    原先的 ``missing_conditions`` 是死字段 —— ``match`` 只返回条件全满足的
    规则，那个字段恒为空，留着只会让人以为存在「部分匹配」这条路径。
    """

    rule: Rule
    traces: tuple[ConditionTrace, ...]

    @property
    def matched_conditions(self) -> tuple[str, ...]:
        return tuple(trace.key for trace in self.traces)

    @property
    def is_fully_traced(self) -> bool:
        """每条条件都能指向具体事实来源。缺来源 = 证据链断了一环。

        **必须要求 traces 非空。** 只写 ``all(trace.sources for ...)`` 时，
        空元组会让 ``all()`` 返回 True —— 「一条 trace 都没有」反而算
        「完全可追溯」。那正是最危险的失败形态：手工拼一个没有追踪的
        RuleMatch 就能让 ``untraced_rule_ids`` 静默为空，证据链看着完整，
        实际上一环都没有。Phase 4.4 的测试逮到了它。
        """
        return bool(self.traces) and all(trace.sources for trace in self.traces)

    def to_dict(self) -> dict[str, Any]:
        """序列化给提示词与 API 用。

        ``urn`` 与 ``citation`` 是**必须**带上的：Phase 4 的提示契约要求模型
        给每条断语挂出处角标，而模型只能引用它拿得到的东西。之前这里只有
        ``source``（一句自由文本），模型无法据此写出可核验的出处 ——
        要么不写脚注，要么自己编一个。两者都比不给更糟。
        """
        return {
            "rule_id": self.rule.id,
            "conclusion": self.rule.conclusion,
            "school": self.rule.school,
            "category": self.rule.category,
            "topic": self.rule.topic,
            "confidence": self.rule.confidence,
            "source": self.rule.source,
            "source_tier": str(self.rule.source_tier),
            "review_status": str(self.rule.review_status),
            "is_production_ready": self.rule.is_production_ready,
            "urn": self.rule.urn or None,
            "citation": self.rule.citation.to_dict() if self.rule.citation else None,
            "conditions": [trace.to_dict() for trace in self.traces],
        }


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
        facts: tuple[Fact, ...],
        *,
        school: str = "",
        category: str = "",
        topic: str = "",
        production_only: bool = False,
    ) -> tuple[RuleMatch, ...]:
        """返回条件全部满足的规则，每条附带条件追踪。

        参数是**事实元组**而不是归并后的字典：追踪需要知道每条条件的取值
        来自哪条事实、哪个命盘要素，这些信息在归并成字典时就丢了。

        ``production_only`` 打开后只匹配 ACTIVE 规则；默认关闭，便于内部
        测试与演示覆盖尚未校核的规则。
        """
        fact_map = group_facts(facts)
        index = index_facts(facts)
        matches: list[RuleMatch] = []
        for rule in self.select(school=school, category=category, topic=topic):
            if production_only and not rule.is_production_ready:
                continue
            traces: list[ConditionTrace] = []
            for key, expected in rule.condition.items():
                actual = fact_map.get(key)
                if not condition_holds(actual, expected):
                    break
                traces.append(
                    ConditionTrace(key, expected, actual, _sources_for(index, key, expected))
                )
            else:
                matches.append(RuleMatch(rule=rule, traces=tuple(traces)))
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

    def validate_topics(self, known: frozenset[str] | set[str]) -> None:
        """拒绝挂在未登记主题上的规则。

        与流派校验同理：主题如果可以是任意字符串，它就会退化成注释 ——
        规则挂着一个没人认识的主题，永远不会被任何分析选中，而且不报错。
        """
        unknown = sorted({rule.topic for rule in self._rules.values()} - set(known))
        if unknown:
            raise ValueError(f"规则库引用了未登记的主题：{'、'.join(unknown)}")

    def fingerprint(self) -> str:
        """规则库内容的指纹：任何一条规则改动都会让它变。

        **为什么需要它。** 每条规则自带 ``version``，但那是**单条**的版本号，
        说明不了「这次分析用的是哪一批规则」。两次分析结论不同时，第一个要排除
        的可能就是「规则库变了」—— 没有指纹，只能靠人去 diff 八十多条规则。

        口径：按规则 id 排序后，对 ``to_dict()`` 的规范化 JSON 取 sha256 前 16 位。
        排序是必须的 —— 字典插入顺序随注册顺序变，不排序会得到「内容一样、
        指纹不同」的假差异。``to_dict()`` 而不是手写字段清单：后者每加一个字段
        就要同步改一次，漏改的后果是指纹对某些改动不敏感（看起来没变，其实变了）。
        """
        payload = [
            json.dumps(rule.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
            for rule in sorted(self._rules.values(), key=lambda item: item.id)
        ]
        digest = hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()
        return digest[:16]

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


def _sources_for(
    index: dict[str, tuple[Fact, ...]], key: str, expected: Any
) -> tuple[str, ...]:
    """回填满足某条条件的事实在命盘里的出处。

    同类型事实可能有多条（一个命盘常同时有六合与自刑），此时只取**取值
    对得上**的那些 —— 把不相关的事实来源一起列出来，等于伪造证据链。

    判据复用 :func:`condition_holds`，而不是另写一个 ``fact.value == expected``：
    后者在「事实值本身是多值元组」时会失效 —— ``ten_god_with_root`` 的取值是
    ``("比肩", "食神")`` 这样的元组，用相等判断去找永远找不到，证据链就断了。
    决定「条件成不成立」和决定「是哪条事实让它成立」必须是同一个谓词，
    否则两处判断会各自漂移。
    """
    facts = index.get(key, ())
    expected_values = (
        expected if isinstance(expected, (list, tuple, set, frozenset)) else (expected,)
    )
    chosen = [
        fact
        for fact in facts
        if any(condition_holds(fact.value, item) for item in expected_values)
    ]
    return tuple(dict.fromkeys(fact.source for fact in chosen))


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
