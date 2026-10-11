"""命理 Analyst/Critic 的本地、可测试实现。

两个 Agent 的职责边界很硬：

- **Analyst** 只把证据翻译成人话，不做新推断。它拿到的每一个说法都必须
  来自 ``evidence.matches``。
- **Critic** 只检查「结论有没有越过证据边界」，不评价命理对错。

Analyst 有两条出稿路径：

1. **确定性模板**（默认，无 provider）：把命中的规则结论按置信度排序后拼成
   摘要。Phase 1-3 的行为，逐字未变。
2. **provider 出稿**（Phase 4 新增）：请求由 :mod:`agents.prompt` 的契约构造，
   模型只拿得到证据链；输出必须过契约校验，越界引用会被记名而不是静默丢弃。
   可选的 Critic 回灌构成多轮修正 —— 但重试同样只给证据链，不追加新信息，
   否则「多轮修正」会变成「多轮加料」。

四条边界：主题覆盖不足必须披露、证据链不能断环、结论引用不得越出证据链、
低强度下必须披露强度。
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.llm import LLMProvider
from agents.prompt import (
    CERTAINTY_WORDS,
    LOW_STRENGTH_CEILING,
    STRENGTH_MARKER,
    Draft,
    build_prompt,
    build_revision_prompt,
    parse_draft,
)
from engines.bazi.models import Chart
from knowledge.evidence import Evidence, build_evidence
from knowledge.rules import RuleMatch, RuleRegistry
from knowledge.topics import TopicStatus

CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
CONCLUSION_LIMIT = 6
"""结论里最多内联多少条规则的原文。

规则库扩容后一个命盘常命中十几条，全部拼进结论会变成一堵墙。这里按置信度
排序后只内联前若干条，其余在证据链里完整可见 —— 摘要可以短，证据不能少。
"""

MAX_REVISIONS = 2
"""Critic 不过时最多重写几轮。

定成有限值而不是「改到通过为止」：无限重试会把一次失败放大成 N 次调用，
而且没有证据表明第 3 轮会比第 2 轮好。到上限就带着未解决的问题返回，
让它出现在 ``critique.issues`` 里，比假装修好了诚实。
"""

DRAFT_TEMPLATE = "template"
DRAFT_LLM = "llm"

CONFLICT_MARKERS = ("分歧", "冲突")
"""结论里出现任一即视为已披露规则冲突。

Phase 3 的检查是「有冲突就拦」，这其实是错的：它拦的不是「没披露」，
而是「存在冲突」这件事本身 —— 而冲突是命盘的真实情况，不是缺陷。
``_summarise`` 明明写了「存在 N 处规则分歧，需并列披露」，却照样被拦下。
Phase 4 把它改成和主题覆盖同一口径：**查披露，不查存在**。
"""


@dataclass(frozen=True)
class Analysis:
    question: str
    evidence: Evidence
    conclusion: str
    certainty_risk: bool = False
    cited_rule_ids: tuple[str, ...] = ()
    draft_source: str = DRAFT_TEMPLATE
    provider: str = ""
    model: str = ""
    revisions: int = 0
    contract_violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Critique:
    passed: bool
    issues: tuple[str, ...]


class AnalystAgent:
    """先构建证据，再生成保守的结构化说明。"""

    def __init__(
        self,
        registry: RuleRegistry,
        provider: LLMProvider | None = None,
        max_revisions: int = MAX_REVISIONS,
    ) -> None:
        if max_revisions < 0:
            raise ValueError("max_revisions 不能为负数。")
        self.registry = registry
        self.provider = provider
        self.max_revisions = max_revisions

    def analyze(
        self, chart: Chart, question: str, *, critic: CriticAgent | None = None
    ) -> Analysis:
        """构建证据并出稿。

        ``critic`` 只在 provider 路径下生效：它构成多轮修正的闭环。
        模板路径不需要 —— 它不会越界，重写也没有意义。
        """
        if not question.strip():
            raise ValueError("问题不能为空。")
        # 问题原文当作主题传入，由 topics.resolve 处理别名（「事业」→ career）。
        # 解析不出主题也不会报错，而是落进「未登记主题」并如实报告覆盖状态。
        evidence = build_evidence(chart, self.registry, topic=question)
        provider = self.provider
        if provider is None:
            conclusion = self._summarise(evidence)
            return Analysis(
                question=question,
                evidence=evidence,
                conclusion=conclusion,
                certainty_risk=_certainty_risk(conclusion),
                cited_rule_ids=self._cited(evidence),
            )
        return self._draft(evidence, question, critic, provider)

    def _ordered(self, evidence: Evidence) -> tuple[RuleMatch, ...]:
        """按置信度排序；同置信度按规则 ID 稳定排序，保证输出可复现。"""
        return tuple(sorted(
            evidence.matches,
            key=lambda match: (CONFIDENCE_RANK[match.rule.confidence], match.rule.id),
        ))

    def _cited(self, evidence: Evidence) -> tuple[str, ...]:
        """模板路径实际内联了哪些规则。

        结论说「基于以下规则」，就必须能报出是哪几条 —— 否则
        「结论能追溯到具体规则」这条验收标准只能靠人去比对文本。
        """
        return tuple(match.rule.id for match in self._ordered(evidence)[:CONCLUSION_LIMIT])

    def _summarise(self, evidence: Evidence) -> str:
        if not evidence.matches:
            return "当前规则库没有匹配到足够结构证据，不能形成可靠结论。"
        ordered = self._ordered(evidence)
        shown = ordered[:CONCLUSION_LIMIT]
        parts = ["基于已匹配的结构规则：" + "；".join(match.rule.conclusion for match in shown)]
        if len(ordered) > CONCLUSION_LIMIT:
            parts.append(f"另有 {len(ordered) - CONCLUSION_LIMIT} 条规则命中，详见证据链。")
        if evidence.conflicts:
            parts.append(f"存在 {len(evidence.conflicts)} 处规则分歧，需并列披露，不做取舍。")
        parts.append(
            f"证据强度 {evidence.strength:.2f}"
            f"（{evidence.strength_breakdown.supporting_rules} 条支持规则）。"
        )
        if evidence.status is not TopicStatus.COVERED:
            parts.append(evidence.coverage_note)
        return " ".join(parts)

    def _draft(
        self,
        evidence: Evidence,
        question: str,
        critic: CriticAgent | None,
        provider: LLMProvider,
    ) -> Analysis:
        """provider 出稿 + 可选多轮修正。

        循环的终止条件有两个：Critic 通过，或重写轮数到上限。到上限时
        **带着未解决的问题返回**，不做「最后一次凑合放行」。
        """
        allowed = frozenset(match.rule.id for match in evidence.matches)
        draft: Draft | None = None
        issues: tuple[str, ...] = ()
        revisions = 0
        while True:
            request = (
                build_prompt(evidence)
                if draft is None
                else build_revision_prompt(evidence, draft, issues)
            )
            draft = parse_draft(provider.complete(request), allowed)
            analysis = Analysis(
                question=question,
                evidence=evidence,
                conclusion=draft.text,
                certainty_risk=_certainty_risk(draft.text),
                cited_rule_ids=draft.cited_rule_ids,
                draft_source=DRAFT_LLM,
                provider=provider.name,
                model=provider.model,
                revisions=revisions,
                contract_violations=draft.violations,
            )
            if critic is None or revisions >= self.max_revisions:
                return analysis
            critique = critic.critique(analysis)
            if critique.passed:
                return analysis
            issues = critique.issues
            revisions += 1


class CriticAgent:
    """检查结论是否越过证据边界。"""

    def critique(self, analysis: Analysis) -> Critique:
        issues: list[str] = []
        evidence = analysis.evidence
        rule_ids = {match.rule.id for match in evidence.matches}

        issues.extend(self._contract_issues(analysis, rule_ids))

        if not analysis.conclusion.strip():
            issues.append("结论为空，无法形成可读输出")

        certainty = [word for word in CERTAINTY_WORDS if word in analysis.conclusion]
        if certainty:
            issues.append(
                "结论包含确定性预测措辞：" + "、".join(certainty)
                + f"（当前证据强度 {evidence.strength:.2f}）"
            )
        if (
            evidence.strength < LOW_STRENGTH_CEILING
            and STRENGTH_MARKER not in analysis.conclusion
        ):
            issues.append(
                f"证据强度仅 {evidence.strength:.2f}，低于 {LOW_STRENGTH_CEILING}，"
                "但结论未披露强度 —— 读者会把弱证据读成强结论"
            )
        if not evidence.matches and analysis.conclusion.startswith("基于"):
            issues.append("结论声称有规则支持，但证据为空")
        if any(rule_id not in rule_ids for rule_id in evidence.to_dict()["rules"]):
            issues.append("存在无法追溯的规则引用")
        if evidence.untraced_rule_ids:
            issues.append(
                "证据链断环，以下规则无法追溯到命盘要素："
                + "、".join(evidence.untraced_rule_ids)
            )
        if evidence.conflicts and not any(
            marker in analysis.conclusion for marker in CONFLICT_MARKERS
        ):
            issues.append(
                f"存在 {len(evidence.conflicts)} 处规则冲突，但结论未向用户披露 —— "
                "冲突是命盘的真实情况，必须并列呈现，不能替用户取舍"
            )
        if evidence.unreviewed_rule_ids:
            issues.append(
                "结论引用了尚未通过校核的规则，不能作为权威依据："
                + "、".join(evidence.unreviewed_rule_ids)
            )
        if evidence.status is not TopicStatus.COVERED and evidence.coverage_note not in analysis.conclusion:
            issues.append(
                f"结论未披露主题覆盖不足（当前状态 {evidence.status}）："
                "该主题没有专属规则，不能让它看起来像是对该主题的判断"
            )
        return Critique(not issues, tuple(issues))

    def _contract_issues(self, analysis: Analysis, rule_ids: set[str]) -> list[str]:
        """契约层违约 + 对 ``cited_rule_ids`` 的独立复算。

        复算不是多余：``parse_draft`` 已经过滤过一次越界引用，但那个保证
        只对「走 parse_draft 的路径」成立。换一个 provider 适配层时若漏掉
        这一步，``contract_violations`` 会是空的，而复算仍然拦得住。
        两处口径必须一致，所以这里只报「违约记录里没提过」的那些，避免同一
        件事被说两遍。
        """
        issues = [f"草稿违反提示契约：{violation}" for violation in analysis.contract_violations]
        strays = [
            rule_id
            for rule_id in analysis.cited_rule_ids
            if rule_id not in rule_ids
            and not any(rule_id in violation for violation in analysis.contract_violations)
        ]
        if strays:
            issues.append("结论引用了证据链之外的规则：" + "、".join(strays))
        return issues


def _certainty_risk(text: str) -> bool:
    """结论里是否出现了禁用词表里的措辞。"""
    return any(word in text for word in CERTAINTY_WORDS)
