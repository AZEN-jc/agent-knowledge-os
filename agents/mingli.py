"""命理 Analyst/Critic 的本地、可测试实现。"""

from __future__ import annotations

from dataclasses import dataclass

from engines.bazi.models import Chart
from knowledge.evidence import Evidence, build_evidence
from knowledge.rules import RuleRegistry

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
        text = "基于已匹配的结构规则：" + "；".join(match.rule.conclusion for match in shown)
        if len(ordered) > CONCLUSION_LIMIT:
            text += f"；另有 {len(ordered) - CONCLUSION_LIMIT} 条规则命中，详见证据链。"
        if evidence.conflicts:
            text += f" 存在 {len(evidence.conflicts)} 处规则分歧，需并列披露，不做取舍。"
        return text


class CriticAgent:
    """检查结论是否越过证据边界。"""

    def critique(self, analysis: Analysis) -> Critique:
        issues: list[str] = []
        rule_ids = {match.rule.id for match in analysis.evidence.matches}
        if "一定" in analysis.conclusion or "必然" in analysis.conclusion:
            issues.append("结论包含确定性预测措辞")
        if not analysis.evidence.matches and analysis.conclusion.startswith("基于"):
            issues.append("结论声称有规则支持，但证据为空")
        if any(rule_id not in rule_ids for rule_id in analysis.evidence.to_dict()["rules"]):
            issues.append("存在无法追溯的规则引用")
        if analysis.evidence.conflicts:
            issues.append("存在规则冲突，必须向用户披露")
        if analysis.evidence.unreviewed_rule_ids:
            issues.append(
                "结论引用了尚未通过校核的规则，不能作为权威依据："
                + "、".join(analysis.evidence.unreviewed_rule_ids)
            )
        return Critique(not issues, tuple(issues))
