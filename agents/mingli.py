"""命理 Analyst/Critic 的本地、可测试实现。

两个 Agent 的职责边界很硬：

- **Analyst** 只把证据翻译成人话，不做新推断。它拿到的每一个说法都必须
  来自 ``evidence.matches``。
- **Critic** 只检查「结论有没有越过证据边界」，不评价命理对错。

本轮新增的两条边界：主题覆盖不足必须披露，且证据链不能断环。
"""

from __future__ import annotations

from dataclasses import dataclass

from engines.bazi.models import Chart
from knowledge.evidence import Evidence, build_evidence
from knowledge.rules import RuleRegistry
from knowledge.topics import TopicStatus

CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
CONCLUSION_LIMIT = 6
"""结论里最多内联多少条规则的原文。

规则库扩容后一个命盘常命中十几条，全部拼进结论会变成一堵墙。这里按置信度
排序后只内联前若干条，其余在证据链里完整可见 —— 摘要可以短，证据不能少。
"""


@dataclass(frozen=True)
class Analysis:
    question: str
    evidence: Evidence
    conclusion: str
    certainty_risk: bool = False


@dataclass(frozen=True)
class Critique:
    passed: bool
    issues: tuple[str, ...]


class AnalystAgent:
    """先构建证据，再生成保守的结构化说明。"""

    def __init__(self, registry: RuleRegistry) -> None:
        self.registry = registry

    def analyze(self, chart: Chart, question: str) -> Analysis:
        if not question.strip():
            raise ValueError("问题不能为空。")
        # 问题原文当作主题传入，由 topics.resolve 处理别名（「事业」→ career）。
        # 解析不出主题也不会报错，而是落进「未登记主题」并如实报告覆盖状态。
        evidence = build_evidence(chart, self.registry, topic=question)
        return Analysis(question, evidence, self._summarise(evidence))

    def _summarise(self, evidence: Evidence) -> str:
        if not evidence.matches:
            return "当前规则库没有匹配到足够结构证据，不能形成可靠结论。"
        ordered = sorted(
            evidence.matches,
            key=lambda match: (CONFIDENCE_RANK[match.rule.confidence], match.rule.id),
        )
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


class CriticAgent:
    """检查结论是否越过证据边界。"""

    def critique(self, analysis: Analysis) -> Critique:
        issues: list[str] = []
        evidence = analysis.evidence
        rule_ids = {match.rule.id for match in evidence.matches}
        if "一定" in analysis.conclusion or "必然" in analysis.conclusion:
            issues.append("结论包含确定性预测措辞")
        if not evidence.matches and analysis.conclusion.startswith("基于"):
            issues.append("结论声称有规则支持，但证据为空")
        if any(rule_id not in rule_ids for rule_id in evidence.to_dict()["rules"]):
            issues.append("存在无法追溯的规则引用")
        if evidence.untraced_rule_ids:
            issues.append(
                "证据链断环，以下规则无法追溯到命盘要素："
                + "、".join(evidence.untraced_rule_ids)
            )
        if evidence.conflicts:
            issues.append("存在规则冲突，必须向用户披露")
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
