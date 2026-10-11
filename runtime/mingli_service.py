"""MingLi Agent 的应用服务层。

统一编排排盘、证据、Analyst 和 Critic；API/Web 层只调用这里，不直接拼装
命理业务对象。

默认**不接任何 provider**：Analyst 走确定性模板，行为与 Phase 3 一致，
本地离线可运行。要启用 LLM 出稿就注入一个 provider（见 :mod:`agents.llm`）——
4A 阶段只有假 provider，真 provider 的接线属于后续工作，所以这里刻意
不读环境变量：没有开关，就没有「以为开了其实没开」的空间。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agents.llm import LLMProvider
from agents.mingli import MAX_REVISIONS, AnalystAgent, CriticAgent
from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from knowledge.default_rules import build_registry, default_schools
from knowledge.rules import RuleRegistry
from knowledge.schools import SchoolRegistry


@dataclass(frozen=True)
class AnalysisResponse:
    chart: dict[str, Any]
    analysis: dict[str, Any]
    critique: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MingLiService:
    """本地命理服务；所有输出都保留 provider、规则和证据来源。"""

    def __init__(
        self,
        registry: RuleRegistry | None = None,
        schools: SchoolRegistry | None = None,
        provider: LLMProvider | None = None,
        max_revisions: int = MAX_REVISIONS,
    ) -> None:
        self.schools = schools if schools is not None else default_schools()
        self.registry = registry if registry is not None else build_registry(schools=self.schools)
        self.calculator = BaziCalculator(SxtwlBaziProvider())
        self.analyst = AnalystAgent(self.registry, provider=provider, max_revisions=max_revisions)
        self.critic = CriticAgent()
        self.provider = provider

    def analyze(self, birth_data: dict[str, Any], question: str) -> AnalysisResponse:
        birth = BirthInput(**birth_data)
        chart = self.calculator.calculate_chart(birth)
        # 把 Critic 交给 Analyst：provider 路径下它构成多轮修正的闭环。
        # 模板路径会忽略这个参数（模板不会越界，重写没有意义）。
        analysis = self.analyst.analyze(chart, question, critic=self.critic)
        critique = self.critic.critique(analysis)
        return AnalysisResponse(
            chart=chart.to_dict(),
            analysis={
                "question": analysis.question,
                "evidence": analysis.evidence.to_dict(),
                "conclusion": analysis.conclusion,
                "draft": {
                    "source": analysis.draft_source,
                    "provider": analysis.provider,
                    "model": analysis.model,
                    "revisions": analysis.revisions,
                    "cited_rules": list(analysis.cited_rule_ids),
                    "contract_violations": list(analysis.contract_violations),
                    "certainty_risk": analysis.certainty_risk,
                },
            },
            critique={"passed": critique.passed, "issues": list(critique.issues)},
        )
