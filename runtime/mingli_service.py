"""MingLi Agent 的应用服务层。

统一编排排盘、证据、Analyst 和 Critic；API/Web 层只调用这里，不直接拼装
命理业务对象。

默认**不接任何 provider**：Analyst 走确定性模板，行为与 Phase 3 一致，
本地离线可运行。要启用 LLM 出稿就注入一个 provider（见 :mod:`agents.llm`）——
4A 阶段只有假 provider，真 provider 的接线属于后续工作，所以这里刻意
不读环境变量：没有开关，就没有「以为开了其实没开」的空间。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

from agents.llm import LLMProvider
from agents.mingli import MAX_REVISIONS, AnalystAgent, CriticAgent
from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from engines.bazi.models import Chart
from engines.bazi.time_engine import ClassicalApproxDayunPolicy
from knowledge.default_rules import build_registry, default_schools
from knowledge.rules import RuleRegistry
from knowledge.schools import SchoolRegistry
from knowledge.time_windows import analyze_period
from knowledge.topics import resolve

#: 多主题并发时线程池的硬顶。与 ``api.server.MAX_TOPICS`` 同一个量级，
#: 但**不 import 它**：服务层不依赖 API 层（方向反了），两边各自定常量、
#: 用测试钉住一致性。
MAX_ANALYSIS_WORKERS = 8


@dataclass(frozen=True)
class AnalysisResponse:
    chart: dict[str, Any]
    analysis: dict[str, Any]
    critique: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicResult:
    """一个主题的分析结果。失败也是一个结果，如实带回原因。"""

    topic: str
    topic_name: str
    ok: bool
    error: str = ""
    analysis: AnalysisResponse | None = None


@dataclass(frozen=True)
class MultiAnalysisResponse:
    """跨主题并发分析的汇总。``chart`` 只出现一次 —— 扇出点在它之后。"""

    chart: dict[str, Any]
    topics: tuple[str, ...]
    results: tuple[TopicResult, ...]

    @property
    def succeeded(self) -> tuple[TopicResult, ...]:
        return tuple(result for result in self.results if result.ok)

    @property
    def failed(self) -> tuple[TopicResult, ...]:
        return tuple(result for result in self.results if not result.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart": self.chart,
            "topics": list(self.topics),
            "results": [
                {
                    "topic": result.topic,
                    "topic_name": result.topic_name,
                    "ok": result.ok,
                    "error": result.error,
                    # chart 已在顶层；每个主题只带 analysis 与 critique，
                    # 不重复那份命盘。
                    "analysis": (
                        {"analysis": result.analysis.analysis,
                         "critique": result.analysis.critique}
                        if result.analysis else None
                    ),
                }
                for result in self.results
            ],
            "succeeded": len(self.succeeded),
            "failed": len(self.failed),
        }


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
        return self._analyze_chart(chart, question)

    def _analyze_chart(self, chart: Chart, question: str) -> AnalysisResponse:
        """在**已算好**的命盘上分析。多主题扇出复用这一条路径，不另写一份。

        ``question`` 同时充当主题：``AnalystAgent`` 把它交给
        ``topics.resolve`` 处理别名（「事业」→ career）。所以多主题调用
        直接把主题名当 question 传，不需要一张「主题 → 问句」的映射表。
        """
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
                    # 两个指纹让报告能回答「这次用的哪版提示词、哪版规则库」。
                    # 模板路径也带 —— 它同样受契约与规则库影响，不能只有 LLM 路径有。
                    "contract_fingerprint": analysis.contract_fingerprint,
                    "rule_fingerprint": analysis.rule_fingerprint,
                },
            },
            critique={"passed": critique.passed, "issues": list(critique.issues)},
        )

    def analyze_multi(
        self, birth_data: dict[str, Any], topics: list[str] | tuple[str, ...]
    ) -> MultiAnalysisResponse:
        """跨主题**并发**分析。命盘只算一次，扇出点在它之后。

        为什么值得并发：主题之间彼此独立，没有跨主题依赖，所以依赖图只有
        一层 —— 不需要 DAG 调度器，一把提交即可。确定性路径下 Python 的
        GIL 让线程拿不到 CPU 并行度，收益主要是**故障隔离**（一个主题炸了
        不影响其余）与**为 I/O 密集的 provider 路径预留形状**；注入真 LLM
        后每个主题是一次网络调用，线程池这时才真正并行。

        ``ponytail:`` 线程池而非进程池 —— 进程池要把规则注册表 pickle 给每个
        任务，而建表要读语料，开销远超收益。provider 必须线程安全：
        ``FakeLLMProvider`` 会 pop/append，并发下会丢脚本；生产 provider
        若要并发，在 provider 内部加锁。

        **线程数封顶。** ``max_workers`` 取 ``min(len(topics),
        MAX_ANALYSIS_WORKERS)`` 而不是裸的 ``len(topics)``：服务层是公开入口，
        API 层虽有 ``MAX_TOPICS`` 拦着，但直接调 ``analyze_multi`` 的调用方
        不受那道约束。没有封顶时，一次调用就能开出任意多个线程 ——
        那不是「支持并发」，那是把调度权交给调用方。
        """
        if not topics:
            raise ValueError("topics 不能为空。")

        birth = BirthInput(**birth_data)
        chart = self.calculator.calculate_chart(birth)
        names = {topic: resolve(topic).name for topic in topics}

        workers = min(len(topics), MAX_ANALYSIS_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [(topic, pool.submit(self._analyze_chart, chart, topic))
                       for topic in topics]
            results: list[TopicResult] = []
            for topic, future in futures:
                try:
                    payload = future.result()
                except Exception as exc:  # 单主题失败不波及其他主题
                    results.append(TopicResult(
                        topic=topic, topic_name=names[topic], ok=False, error=str(exc),
                    ))
                else:
                    results.append(TopicResult(
                        topic=topic, topic_name=names[topic], ok=True, analysis=payload,
                    ))

        return MultiAnalysisResponse(
            chart=chart.to_dict(), topics=tuple(topics), results=tuple(results)
        )

    def analyze_timeline(
        self,
        birth_data: dict[str, Any],
        start_year: int,
        end_year: int,
        topic: str,
    ) -> tuple[Any, ...]:
        """分析某个年份区间内每一年的结构信号。

        **有性别才算大运**，没有就只算流年。顺逆规则不同流派有分歧，
        缺性别时不猜默认方向 —— 与 ``analyze_period`` 的口径一致。
        """
        birth = BirthInput(**birth_data)
        chart = self.calculator.calculate_chart(birth)
        policy = ClassicalApproxDayunPolicy() if birth.gender else None
        return analyze_period(chart, start_year, end_year, topic, dayun_policy=policy)
