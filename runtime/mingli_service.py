"""MingLi Agent 的应用服务层。

统一编排排盘、证据、Analyst 和 Critic；API/Web 层只调用这里，不直接拼装
命理业务对象。默认不接外部 LLM，保证本地离线可运行。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agents.mingli import AnalystAgent, CriticAgent
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
    ) -> None:
        self.schools = schools if schools is not None else default_schools()
        self.registry = registry if registry is not None else build_registry(schools=self.schools)
        self.calculator = BaziCalculator(SxtwlBaziProvider())
        self.analyst = AnalystAgent(self.registry)
        self.critic = CriticAgent()

    def analyze(self, birth_data: dict[str, Any], question: str) -> AnalysisResponse:
        birth = BirthInput(**birth_data)
        chart = self.calculator.calculate_chart(birth)
        analysis = self.analyst.analyze(chart, question)
        critique = self.critic.critique(analysis)
        return AnalysisResponse(
            chart=chart.to_dict(),
            analysis={
                "question": analysis.question,
                "evidence": analysis.evidence.to_dict(),
                "conclusion": analysis.conclusion,
            },
            critique={"passed": critique.passed, "issues": list(critique.issues)},
        )
