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

from agents.llm import LLMProvider, ProviderError
from agents.prompt import (
    CERTAINTY_WORDS,
    FOOTNOTE_CLOSE,
    FOOTNOTE_OPEN,
    FOOTNOTE_PATTERN,
    LOW_STRENGTH_CEILING,
    STRENGTH_MARKER,
    Draft,
    build_prompt,
    build_revision_prompt,
    contract_fingerprint,
    parse_draft,
)
from engines.bazi.models import Chart
from knowledge.evidence import Evidence, build_evidence
from knowledge.provenance import SourceTier
from knowledge.rules import RuleMatch, RuleRegistry
from knowledge.topics import STRUCTURAL_TOPIC, TopicStatus

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
    contract_fingerprint: str = ""
    """本次出稿所用的提示契约指纹。

    与 :attr:`rule_fingerprint` 成对出现：两份分析结论不同时，先要能排除
    「输入变了」这个解释。没有它们，只能靠人逐条比对提示词与规则库。
    """
    rule_fingerprint: str = ""
    """本次匹配所用的规则库指纹（``RuleRegistry.fingerprint()``）。"""
    degraded_reason: str = ""
    """降级原因；空串表示没有降级。

    **为什么单独一个字段而不是塞进 ``contract_violations``。** 两者是不同
    性质的事：违约是「模型越界了」，降级是「模型根本没说话」。混在一起，
    读者分不清「这段话是模型说的但不合规」与「这句话是模板说的」。

    Phase 4.5：provider 故障（网络、超时、非 200、响应形状不对）时降级到
    确定性模板出稿，并把原因写在这里。**不伪装成分析成功** —— 用户看得见
    这次没走模型，也看得见为什么。
    """


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
        # 两个指纹在构造时算一次，不放在 analyze 里 —— 规则库指纹要序列化
        # 全部规则，每次分析都算是白烧。registry 是不可变的（分析途中不增删规则），
        # 缓存它安全。
        self.contract_fingerprint = contract_fingerprint()
        self.rule_fingerprint = registry.fingerprint()

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
            return self._template_analysis(question, evidence)
        return self._draft(evidence, question, critic, provider)

    def _template_analysis(
        self, question: str, evidence: Evidence, degraded_reason: str = ""
    ) -> Analysis:
        """用确定性模板出稿。

        两条路会走到这里：**没有 provider**（本来就走模板），以及
        **provider 故障时降级**（Phase 4.5）。抽成方法是因为这两条路必须
        逐字段一致 —— 各写一遍的话，降级路径会悄悄少个字段，而那种偏差
        只在故障时出现，测试稍不留神就漏过去。
        """
        conclusion = self._summarise(evidence)
        return Analysis(
            question=question,
            evidence=evidence,
            conclusion=conclusion,
            certainty_risk=_certainty_risk(conclusion),
            cited_rule_ids=self._cited(evidence),
            contract_fingerprint=self.contract_fingerprint,
            rule_fingerprint=self.rule_fingerprint,
            degraded_reason=degraded_reason,
        )

    def _domain_rule_ids(self, evidence: Evidence) -> set[str]:
        """主题层规则的 ID 集合。

        问公共结构层时主题层与基础层**重合**，此时返回空集 —— 否则「典籍断语」
        这个标签会把全部结构规则都算进去，标签又变成谎话（这正是 Phase 3 修掉的
        那类问题）。``Evidence.domain_matches`` 已经处理了这层重合，
        这里只需把「基础层不算主题层」这件事在排序上落实。
        """
        if evidence.topic_id == STRUCTURAL_TOPIC:
            return set()
        return {match.rule.id for match in evidence.domain_matches}

    def _ordered(self, evidence: Evidence) -> tuple[RuleMatch, ...]:
        """排序：**主题层优先** → 置信度 → 规则 ID。

        主题层必须排最前。纯按置信度排会把典籍断语挤进「另有 N 条」里 ——
        典籍断语的置信度是 MEDIUM，而结构层命中里 HIGH 一大片。用户问「命局」，
        典籍断语才是答案，结构层是背景。把答案藏在「详见证据链」后面，
        等于没给答案。
        """
        domain_ids = self._domain_rule_ids(evidence)
        return tuple(sorted(
            evidence.matches,
            key=lambda match: (
                0 if match.rule.id in domain_ids else 1,
                CONFIDENCE_RANK[match.rule.confidence],
                match.rule.id,
            ),
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
        domain_ids = self._domain_rule_ids(evidence)
        domain_shown = [match for match in shown if match.rule.id in domain_ids]
        base_shown = [match for match in shown if match.rule.id not in domain_ids]

        parts: list[str] = []
        if domain_shown:
            # 典籍断语必须带出处角标：结论里每一句「典籍说」都要能点回去。
            # 不挂 URN 的典籍断语和「我听说」没有区别。
            parts.append("典籍断语（附出处）：" + "；".join(
                f"{match.rule.conclusion}〔{match.rule.urn}〕" for match in domain_shown
            ))
        if base_shown:
            parts.append("基于已匹配的结构规则：" + "；".join(
                match.rule.conclusion for match in base_shown
            ))
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
            try:
                raw = provider.complete(request)
            except ProviderError as exc:
                # Phase 4.5：provider 故障 → 降级到确定性模板，并如实记录。
                #
                # 为什么降级而不是把异常抛给调用方：排盘、规则、证据链全是
                # 确定性的，它们没坏。坏掉的只是「把证据复述成自然语言」这
                # 一步，而模板本来就能做这件事。让用户什么都拿不到，比让他
                # 拿到一份标明「本次未走模型」的分析更糟。
                #
                # 为什么只捕 ProviderError：代码 bug（比如传了个 None）
                # 必须响亮地炸。降级会把 bug 藏成一次「故障」，那比崩溃
                # 难查得多。
                # draft 为 None → 这是第 1 次请求（首次出稿）。
                # 否则 revisions 就是「第几轮重写」：revisions=1 表示刚跑完
                # 第一轮审查、正在发第 1 次重写请求。写成 revisions + 1 会把
                # 第 1 轮重写报成「第 2 轮」，用户按消息去找日志会对不上。
                stage = "首次出稿" if draft is None else f"第 {revisions} 轮重写"
                return self._template_analysis(
                    question,
                    evidence,
                    degraded_reason=(
                        f"{stage}时 provider「{provider.name}」不可用"
                        f"（{provider.model}）：{exc}"
                    ),
                )
            draft = parse_draft(raw, allowed)
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
                contract_fingerprint=self.contract_fingerprint,
                rule_fingerprint=self.rule_fingerprint,
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
        issues.extend(self._provenance_issues(analysis))

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

    def _provenance_issues(self, analysis: Analysis) -> list[str]:
        """典籍断语的出处角标，**双向**校验。

        结构层规则可以自证：它的条件就写在证据链里，读者能顺着 ``conditions``
        一路点回命盘要素。典籍规则不行 —— 它引用的是别处的文本，不给出处，
        读者只能选择信或不信，而「信或不信」正是这套系统要消灭的东西。

        两个方向都要查，因为它们是两种不同的失败：

        * **该挂没挂** —— 结论说了「古法记为子遥巳格」，却不说是哪本书哪一卷。
          读者无法回查，这句话和道听途说没有区别。
        * **挂了但不该挂** —— 结论里出现证据链之外的 URN。这是编造出处，
          比不挂更糟：它伪装成可核验的样子。

        只查 ``cited_rule_ids`` 里的规则，不查全部命中规则：没写进结论的规则
        本来就不需要角标，要求它们挂等于逼模型把没说的话也标注一遍。
        """
        cited = set(analysis.cited_rule_ids)
        known = {
            match.rule.urn
            for match in analysis.evidence.matches
            if match.rule.urn
        }

        missing: list[str] = []
        for match in analysis.evidence.matches:
            rule = match.rule
            if rule.id not in cited or rule.source_tier is not SourceTier.CLASSICAL:
                continue
            if not rule.urn:
                # 规则自己没有 URN —— 这是加载期的漏洞（rule_atoms 的引证
                # 守卫本该拦住），不是模型的错。但结论里同样不能就这么算了。
                missing.append(f"{rule.id} 没有可引用的 URN")
                continue
            if f"{FOOTNOTE_OPEN}{rule.urn}{FOOTNOTE_CLOSE}" not in analysis.conclusion:
                missing.append(f"{rule.id} 需挂 {FOOTNOTE_OPEN}{rule.urn}{FOOTNOTE_CLOSE}")

        issues: list[str] = []
        if missing:
            issues.append(
                "典籍断语未挂出处角标，读者无法回查原文：" + "；".join(missing)
            )

        mentioned = set(FOOTNOTE_PATTERN.findall(analysis.conclusion))
        stray = sorted(mentioned - known)
        if stray:
            issues.append(
                "结论引用了证据链之外的出处，疑似编造：" + "、".join(stray)
            )
        return issues

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
