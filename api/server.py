"""MingLi Agent 的本地 FastAPI 入口。

文档：OpenAPI 描述由类型标注与 pydantic 模型自动生成，Swagger UI 在 ``/docs``，
原始描述在 ``/openapi.json``。

错误约定：输入不合法、超出历法库支持范围、或 provider 不可用时一律返回
``422``，``detail`` 为可直接展示给用户的中文说明；不存在的资源返回 ``404``。
不返回 500 堆栈。请求模型层的校验失败另带 ``fields`` 数组
（``[{"field": "month", "message": "…"}]``，Phase 5.2），供前端逐字段定位；
服务层的 422 只有 ``detail`` —— 那一层的问题是整请求的，不是哪个输入框。

**provider 故障的处置分两层**（Phase 4.5）：服务层先降级到确定性模板出稿，
并把原因写进 ``analysis.draft.degraded_reason`` —— 排盘、规则、证据链都是
确定性的，坏的只是复述那一步。只有当降级本身也失败时才走上面的 422。
把 provider 网络失败伪装成一次正常的模型分析，是明令禁止的。

**这条约定曾经只成立了一半。** 状态码那一半一直成立，``detail`` 那一半不成立：
pydantic 在请求模型层拦下的错误，``detail`` 原样是英文技术消息的 dict 列表。
本文件末尾的 :func:`on_validation_error` 把它转成中文说明 ——
修的不是状态码，是让行为符合本文件自己写下的承诺。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.prompt import contract as llm_contract
from knowledge.classical_backlog import CLASSICAL_BACKLOG, BacklogStatus, next_action
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.topics import TOPICS
from runtime.mingli_service import MingLiService
from runtime.report import build_report, render_pdf, report_json

#: 引擎支持范围的两个窄窗口（Phase 3.1 修好历法换算后的剩余边界）。
#:
#: 修好之后引擎已支持 1–9999 年，但区间两端各有一小段走不通，且**日期相关**，
#: 没法用 ``ge``/``le`` 表达：
#:
#: - 第 1 年小寒之前：前一个「节」落在第 0 年，``datetime`` 表示不了。
#: - 第 9999 年小寒（12-31 21:14）之后：后一个「节」落在第 10000 年，同上。
#:   只影响需要「之后」的路径（大运起运年龄），排盘本身不受影响。
#:
#: 所以 ``year`` / ``start_year`` / ``end_year`` 取 ``ge=2, le=9997`` ——
#: 这是「每一条路径都能走通」的区间，不是引擎的理论上限。
#: 两个窗口的报错是人能读懂的中文，见
#: ``tests/test_api_boundaries.py::test_boundary_windows_fail_with_a_readable_reason``。
POLICY_YEAR_RANGE: tuple[int, int] = (2, 9997)

#: 「消息里有没有中文」的判据。见 :func:`_to_user_message`。
CJK_SEARCH = re.compile(r"[\u4e00-\u9fff]")

#: 单次请求可分析的最大主题数。六个已登记主题之外留了余量；
#: 上限的意义是给线程池一个硬顶（服务层同时用它做 max_workers 的封顶）。
MAX_TOPICS = 8

#: 时间轴单次请求的最大跨度。再长的区间应分段请求，而不是让一次调用
#: 循环几十年 —— 那既是超时风险，也是把客户端的分页责任推给服务端。
MAX_TIMELINE_SPAN = 50

#: 问题文本的最大长度。问句不需要一篇作文；没有上限时一个超大字符串
#: 会一路走到证据层才被拒。
MAX_QUESTION_LENGTH = 200

#: 单个主题名的最大长度。主题名是「事业」「财运」这类短词，二十字足够；
#: 没有上限时一个字符串会被当成未知主题原样带到解析层。
MAX_TOPIC_LENGTH = 20

UNPROCESSABLE: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "出生信息非法、超出历法库支持范围，或排盘 provider 不可用。",
    }
}

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"description": "指定的规则 ID 不存在。"},
}


class BirthRequest(BaseModel):
    """出生信息。时间按出生地当地民用时解释（含历史夏令时）。"""

    model_config = ConfigDict(extra="forbid")

    # ge/le 是**策略边界**（全路径可用区间），不是引擎上限：Phase 3.1 修好节气
    # 历法换算后引擎已支持 1–9999 年，两端各有一个窄窗口走不通，
    # 见 POLICY_YEAR_RANGE 的说明。
    #
    # 教训留在代码里：第一版这里写的是 ge=1, le=9999，两条都错 —— year=1 与
    # year=9999/9998 本身就是失败年（引擎内部 +1 后越界）。是
    # tests/test_api_boundaries.py 里「边界内年份应可用」那条测出来的。
    year: int = Field(ge=POLICY_YEAR_RANGE[0], le=POLICY_YEAR_RANGE[1],
                      description="公历年", examples=[1990])
    month: int = Field(ge=1, le=12, description="公历月", examples=[6])
    day: int = Field(ge=1, le=31, description="公历日", examples=[15])
    hour: int = Field(ge=0, le=23, description="当地民用时的时", examples=[14])
    minute: int = Field(default=0, ge=0, le=59, description="当地民用时的分", examples=[30])
    longitude: float | None = Field(
        default=None, ge=-180, le=180, description="经度；仅在开启真太阳时校正时需要"
    )
    latitude: float | None = Field(default=None, ge=-90, le=90, description="纬度")
    timezone: str = Field(
        default="Asia/Shanghai", max_length=64,
        description="IANA 时区名", examples=["Asia/Shanghai"],
    )
    gender: str | None = Field(
        default=None, max_length=16, description="性别；计算大运顺逆时需要", examples=["男"]
    )
    true_solar_time: bool = Field(
        default=False,
        description=(
            "是否按真太阳时排盘（默认关）。开启后必须同时提供 longitude —— "
            "真太阳时校正依赖经度，缺了它只能拒绝，不能猜。算法版本号会带 "
            "+tst 后缀，两张不同口径的命盘不会共用一个版本号。"
        ),
        examples=[False],
    )

    @model_validator(mode="after")
    def _true_solar_time_needs_longitude(self) -> BirthRequest:
        """开启真太阳时校正时必须提供经度。

        为什么在请求模型层拦：引擎的 ``SxtwlBaziProvider`` 也会拒
        （``开启真太阳时必须提供 longitude``），但在那之前 ``BirthInput``
        已经构造成功 —— 错误会以「排盘失败」的面目出现，把配置错误伪装成
        数据错误。在这里拦，用户看到的是一句直指经度字段的中文。

        消息里带「经度」两个字，不依赖 ``FIELD_LABELS`` 的映射 —— 这条
        错误是模型级的（``loc`` 为空），字段定位本来就走兜底分支。
        """
        if self.true_solar_time and self.longitude is None:
            raise ValueError("开启真太阳时校正必须填写经度（longitude）。")
        return self


class AnalyzeRequest(BirthRequest):
    """命盘 + 问题。结论必须能追溯到命盘事实与规则，不做确定性预测。"""

    question: str = Field(
        min_length=1, max_length=MAX_QUESTION_LENGTH,
        description="要分析的问题", examples=["事业如何？"],
    )


class CitationResponse(BaseModel):
    """规则的文献出处。``original_text`` 与 ``url`` 同时具备才算可核验。"""

    book: str = Field(description="典籍名")
    edition: str = Field(description="底本或版本")
    chapter: str = Field(default="", description="卷 / 章 / 篇")
    original_text: str = Field(default="", description="逐字原文摘录")
    url: str = Field(default="", description="可打开的出处地址")
    retrieved_on: str | None = Field(default=None, description="抓取日期（ISO 8601）")


class RuleResponse(BaseModel):
    """一条规则的完整可追溯信息。"""

    id: str
    version: str
    source: str = Field(description="来源描述；结构层写明由哪张定义表唯一确定")
    school: str = Field(description="所属流派 ID；见 /api/schools")
    category: str
    topic: str
    condition: dict[str, Any] = Field(description="条件表达式；键必须在事实词表内")
    conclusion: str
    confidence: str = Field(description="LOW / MEDIUM / HIGH；表示证据等级，不是事件概率")
    source_tier: str = Field(description="structural（可执行验证）/ classical（需典籍原文）")
    review_status: str = Field(description="UNREVIEWED / REVIEWED / ACTIVE / DEPRECATED")
    conflicts_with: list[str]
    evidence_required: list[str]
    citation: CitationResponse | None = None
    urn: str | None = Field(
        default=None, description="典籍规则的规范引用标识；结构层为 null"
    )
    conflict_slot: str = ""
    conflict_value: str = ""
    note: str = ""


class RuleListResponse(BaseModel):
    total: int = Field(description="本次过滤后的规则条数")
    filters: dict[str, str] = Field(description="本次实际生效的过滤条件")
    rules: list[RuleResponse]


class SchoolResponse(BaseModel):
    """一个流派的元数据。"""

    id: str
    name: str
    method: str
    classics: list[str] = Field(description="代表典籍；为空表示无公有领域文本可引")
    divergences: list[str] = Field(description="已知与其他流派的分歧点")
    note: str


class SchoolListResponse(BaseModel):
    total: int
    schools: list[SchoolResponse]


class BacklogEntryResponse(BaseModel):
    """一条待录入的典籍来源，以及它卡在哪一步。"""

    id: str
    book: str
    priority: int
    topic: str
    status: str
    blocker: str
    needed_action: str


class BacklogResponse(BaseModel):
    total: int
    blocked: int = Field(description="当前被阻塞的条目数")
    next_action: str = Field(description="按优先级下一步应处理的书目")
    entries: list[BacklogEntryResponse]


class TopicResponse(BaseModel):
    """一个分析主题，以及它有没有可用的规则。"""

    id: str
    name: str
    description: str
    aliases: list[str] = Field(description="可用作主题入参的别名，含中文")
    blocked_by: str = Field(description="主题层为空时的原因")


class TopicListResponse(BaseModel):
    total: int
    note: str = Field(description="主题覆盖状态的含义说明")
    topics: list[TopicResponse]


class ConditionTraceResponse(BaseModel):
    """一条条件被满足的完整依据。"""

    key: str = Field(description="条件键，对应事实词表里的一个键")
    expected: Any = Field(description="规则要求的值")
    actual: Any = Field(description="命盘实际给出的值")
    sources: list[str] = Field(description="该事实在命盘里的出处，形如 chart.pillars.month")


class RuleChainResponse(BaseModel):
    """证据链的一环：结论 → 规则 → 条件 → 命盘要素。

    ``urn`` 与 ``citation`` 必须随链返回。知识层的 ``RuleMatch.to_dict``
    注释写明这两项是「必须」：没有它们，模型要么不写出处角标，要么自己编
    一个 —— 两者都比不给更糟。API 早先把它们裁掉了（``EvidenceResponse``
    是 ``extra="ignore"``），于是「可验证的出处」在服务层成立、在 API 层
    消失。这是 2026-10-16 补的。
    """

    rule_id: str
    conclusion: str
    school: str
    category: str
    topic: str
    confidence: str = Field(description="证据等级，不是事件概率")
    source: str
    source_tier: str
    review_status: str
    is_production_ready: bool
    urn: str | None = Field(default=None, description="典籍规则的规范引用标识；结构层为 null")
    citation: CitationResponse | None = Field(
        default=None, description="文献出处；结构层为 null。original_text 与 url 同时具备才算可核验"
    )
    conditions: list[ConditionTraceResponse] = Field(
        description="证据链的最后一跳：每条条件的命盘取值与出处"
    )


class StrengthBreakdownResponse(BaseModel):
    """证据强度的完整算式，逐项可核对。"""

    supporting_rules: int
    raw_support: float = Field(description="各命中规则置信度分值之和")
    saturation_k: float = Field(description="饱和常数；本实现选定的标度，不是概率刻度")
    after_saturation: float
    conflicts: int
    conflict_penalty: float
    final: float = Field(description="最终强度，值域 [0, 1)；这是证据等级，不是事件概率")


class FactResponse(BaseModel):
    """一条命盘事实。``source`` 是回溯到命盘要素的最后一跳。"""

    type: str
    value: Any
    source: str
    confidence: float


class EvidenceResponse(BaseModel):
    """证据层输出：事实、证据链、冲突、强度与主题覆盖。"""

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(description="调用方传入的原始主题，可能是别名")
    topic_id: str = Field(description="解析后的规范主题 ID")
    topic_name: str
    status: str = Field(description="covered / base_only / unknown")
    coverage_note: str = Field(description="主题覆盖说明；非 covered 时必须向用户披露")
    schools: list[str]
    facts: list[FactResponse]
    chain: list[RuleChainResponse] = Field(description="完整证据链，可逐条回溯到命盘要素")
    base_rules: list[str] = Field(description="命中的公共结构层规则")
    domain_rules: list[str] = Field(description="命中的主题专属规则；当前恒为空")
    unreviewed_rules: list[str]
    untraced_rules: list[str] = Field(description="证据链断环的规则；正常情况下恒为空")
    conflicts: list[list[str]]
    conflict_notes: list[str]
    strength: float
    strength_breakdown: StrengthBreakdownResponse


class DraftResponse(BaseModel):
    """结论草稿的生成元信息。

    ``cited_rules`` 必定是 ``evidence.chain`` 里规则 ID 的子集 ——
    这一条由契约层保证，Critic 会独立复算一遍。

    两个指纹是**加法式新增**（Phase 4.3）：服务层本来就产出，此前 API 的
    响应模型没声明，被 ``extra="ignore"`` 静默裁掉 —— 于是「报告能说明用了
    哪版提示词、哪版规则库」这件事在 API 侧断了。补上之后，消费者可以直接
    引用它们，也使得 API 响应与服务层响应逐字段一致
    （``test_api_multi_matches_a_direct_call`` 守这一点）。
    """

    source: str = Field(description="template（确定性模板）或 llm（provider 出稿）")
    provider: str = Field(description="provider 名称；模板路径下为空字符串")
    model: str = Field(description="模型标识；模板路径下为空字符串")
    revisions: int = Field(description="为通过审查而重写的轮数；0 表示一次通过")
    cited_rules: list[str] = Field(description="结论引用的规则 ID，必定是证据链的子集")
    contract_violations: list[str] = Field(
        description="提示契约的违约记录；空列表表示没有越界引用"
    )
    certainty_risk: bool = Field(description="结论是否含禁用词表里的确定性措辞")
    contract_fingerprint: str = Field(
        default="",
        description="提示契约指纹；契约内容（提示词/schema/边界规则）任一改动都会变",
    )
    rule_fingerprint: str = Field(
        default="", description="规则库指纹；规则内容任一改动都会变"
    )
    degraded_reason: str = Field(
        default="",
        description=(
            "降级原因；空串表示未降级。非空表示本次未走模型"
            "（provider 故障或 token 预算耗尽），结论由确定性模板产出"
        ),
    )
    prompt_tokens: int = Field(
        default=0, ge=0, description="本次分析消耗的提示 token 数（估算值）"
    )
    completion_tokens: int = Field(
        default=0, ge=0, description="本次分析消耗的输出 token 数（估算值）"
    )
    provider_calls: int = Field(
        default=0, ge=0, description="真正打到 provider 的调用次数；缓存命中不计数"
    )
    served_from_cache: bool = Field(
        default=False,
        description="结论是否来自响应缓存；模型可能不确定，缓存命中必须看得见",
    )


class AnalysisPayload(BaseModel):
    question: str
    evidence: EvidenceResponse
    conclusion: str
    draft: DraftResponse


class AnalysisResponse(BaseModel):
    chart: dict[str, Any]
    analysis: AnalysisPayload
    critique: dict[str, Any]


class TimelineRequest(BirthRequest):
    """生辰 + 年份区间 + 主题。"""

    start_year: int = Field(
        ge=POLICY_YEAR_RANGE[0], le=POLICY_YEAR_RANGE[1],
        description="起始公历年", examples=[2024],
    )
    end_year: int = Field(
        ge=POLICY_YEAR_RANGE[0], le=POLICY_YEAR_RANGE[1],
        description="结束公历年", examples=[2030],
    )
    topic: str = Field(
        default="财运", max_length=MAX_TOPIC_LENGTH,
        description="分析主题，可为中文别名", examples=["财运"],
    )

    @model_validator(mode="after")
    def _span_must_be_bounded(self) -> TimelineRequest:
        """起止年份相差超限时明确拒绝，而不是让服务端循环几十年。

        判据用**年份差**（``end - start``）而不是年份个数：前者是
        ``start_year > end_year`` 被拒之后剩下的唯一上界，语义也更好说清 ——
        相差 50 年即 51 个年份。用 inclusive 计数会多一次 off-by-one 的
        机会，而这里的文案必须让用户能自己算准。

        ``start_year > end_year`` 不在这里管 —— 那一类由 ``analyze_period``
        用中文报出，且已有测试钉住。这里只管上界。
        """
        span = self.end_year - self.start_year
        if span > MAX_TIMELINE_SPAN:
            raise ValueError(
                f"起始年与结束年最多相差 {MAX_TIMELINE_SPAN} 年"
                f"（即至多 {MAX_TIMELINE_SPAN + 1} 个年份）；"
                f"当前请求 {self.start_year}–{self.end_year} 相差 {span} 年，请分段查询。"
            )
        return self


class SignalResponse(BaseModel):
    """一条结构信号：描述「出现了什么」，不描述「会发生什么」。"""

    name: str = Field(description="信号名，如「财星坐流年」「六合巳」")
    label: str = Field(description="含轴名的信号名，如「流年财星坐流年」")
    axis: str = Field(description="liunian（流年）/ dayun（大运）")
    kind: str = Field(description="来源事实键，决定主题过滤怎么处理它")
    detail: str = Field(description="可读说明，含干支与十神")
    source: str = Field(description="回溯到时间轴要素的最后一跳，形如 time.liunian.heavenly_stem")


class TimeWindowResponse(BaseModel):
    """一年的结构信号汇总。"""

    year: int
    topic: str
    topic_name: str
    liunian: dict[str, Any] = Field(description="该年流年干支与 provider")
    dayun: dict[str, Any] | None = Field(
        description="该年所处大运；未提供性别时为 null —— 顺逆规则需流派选择，不猜默认方向"
    )
    signals: list[SignalResponse]
    strength: float = Field(description="证据强度，值域 [0, 1)；是证据等级，不是事件概率")
    strength_breakdown: StrengthBreakdownResponse
    report: str = Field(description="单行摘要；不含任何必然性措辞")


class TimelineResponse(BaseModel):
    total: int
    topic: str
    topic_name: str
    windows: list[TimeWindowResponse]
    note: str


class LLMContractResponse(BaseModel):
    """LLM 提示契约本身。

    把契约作为数据暴露出来，是为了让它可审计：一份只写在源码注释里的契约
    等于没有契约 —— 读 API 的人无法确认模型到底能看到什么。
    """

    version: str
    system_prompt: str = Field(description="每次请求都原样发送的系统提示词")
    draft_schema: dict[str, Any] = Field(description="模型输出必须满足的 JSON Schema")
    boundary: list[str] = Field(description="契约的边界规则清单")
    forbidden_certainty_words: list[str] = Field(description="任意强度下都禁用的措辞")
    strength_marker: str = Field(description="结论里必须出现的强度披露标记")
    low_strength_ceiling: float = Field(description="低于此强度必须披露强度")
    notes: list[str]


service = MingLiService()
app = FastAPI(
    title="MingLi Agent API",
    version="0.1.0",
    summary="可验证的命理推理服务",
    description=(
        "确定性排盘（不让模型算命盘）→ 事实提取 → 规则匹配 → 证据链。"
        "每个结论都带证据强度与规则来源，不保证预测准确率。"
    ),
)


@app.get("/api/health", summary="健康检查", tags=["运维"])
def health() -> dict[str, str]:
    """返回服务状态与当前排盘 provider。"""
    return {"status": "ok", "provider": "sxtwl"}


def _birth_fields(request: BirthRequest, *extra: str) -> dict[str, Any]:
    """剥掉排盘口径开关与派生字段的出生信息字典。

    ``true_solar_time`` 是**怎么排盘**的开关，不是**什么时候出生**的信息：
    引擎的 ``BirthInput`` 没有这个字段，混在字典里传进服务层会以
    ``TypeError`` 炸开，再被端点捕获成一次「排盘失败」—— 把配置错误
    伪装成数据错误。剥下来单独作为关键字参数传（Phase 5.2）。

    ``extra`` 给派生字段用：``/api/report`` 的 ``topics``/``format`` 与
    ``/api/analyze`` 的 ``question`` 同属请求侧的附加参数，同样不是出生
    信息（Phase 5.7 补这个口子——第一版忘了剥，422 的报错是
    「BirthInput 收到意外参数 topics」）。
    """
    return request.model_dump(exclude={"true_solar_time", *extra})


@app.post(
    "/api/chart",
    summary="排盘",
    description="根据出生信息计算四柱、藏干、十神、纳音与四支关系。",
    tags=["排盘"],
    responses=UNPROCESSABLE,
)
def chart(request: BirthRequest) -> dict[str, Any]:
    try:
        response = service.analyze(
            _birth_fields(request), "命盘结构",
            true_solar_time=request.true_solar_time,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=_to_user_message(exc)) from exc
    return response.chart


@app.post(
    "/api/analyze",
    summary="按问题分析",
    description=(
        "在排盘基础上提取事实、匹配规则、形成证据链，"
        "返回事实、完整证据链（每条规则的条件与命盘出处）、证据强度算式、"
        "冲突与审查结果。\n\n"
        "``evidence.status`` 说明该主题有没有专属规则：``base_only`` 表示"
        "只有公共结构层证据，此时结论不构成对该主题的判断，"
        "``evidence.coverage_note`` 里写了原因。\n\n"
        "``analysis.draft`` 说明结论是怎么来的：``source=template`` 是确定性"
        "模板（默认，离线），``source=llm`` 是 provider 出稿。后者的"
        "``cited_rules`` 必定是证据链的子集，越界引用会出现在"
        "``contract_violations`` 里并由 Critic 披露。当前服务未注入 provider，"
        "因此默认恒为 ``template``；契约见 ``GET /api/llm/contract``。"
    ),
    tags=["分析"],
    response_model=AnalysisResponse,
    responses=UNPROCESSABLE,
)
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    try:
        response = service.analyze(
            request.model_dump(exclude={"question", "true_solar_time"}),
            request.question,
            true_solar_time=request.true_solar_time,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=_to_user_message(exc)) from exc
    return response.to_dict()


@app.post(
    "/api/timeline",
    summary="流年时间轴",
    description=(
        "分析 ``[start_year, end_year]`` 内每一年的结构信号：流年干支对日主的十神、"
        "该十神在四支有没有根、流年支与命盘四支的结构关系（冲太岁等）。\n\n"
        "**信号是结构描述，不是预测** —— 输出形如「2028年，信号：财星坐流年、"
        "六合巳、相破巳，证据强度0.38」。没有任何一处会给出必然性判断。\n\n"
        "``strength`` 是证据等级，不是事件概率；它与 ``/api/analyze`` 的强度"
        "共用同一个算式，两个数字可以互相比较。\n\n"
        "``dayun`` 为 ``null`` 表示未提供 ``gender``：大运顺逆规则不同流派有分歧，"
        "缺性别时不猜默认方向，此时只报流年。提供 ``gender`` 即启用大运，"
        "结果带 ``approximate: true`` 标注（三日折一年的近似口径）。\n\n"
        "地支关系信号（冲太岁等）在**所有主题下都会保留** —— 它的存在不取决于"
        "用户问的是财运还是事业；按主题过滤只作用在十神类信号上。"
    ),
    tags=["时间轴"],
    response_model=TimelineResponse,
    responses=UNPROCESSABLE,
)
def timeline(request: TimelineRequest) -> dict[str, Any]:
    try:
        windows = service.analyze_timeline(
            request.model_dump(
                exclude={"start_year", "end_year", "topic", "true_solar_time"}
            ),
            request.start_year,
            request.end_year,
            request.topic,
            true_solar_time=request.true_solar_time,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=_to_user_message(exc)) from exc

    return TimelineResponse(
        total=len(windows),
        topic=windows[0].topic,
        topic_name=windows[0].topic_name,
        windows=[TimeWindowResponse(**window.to_dict()) for window in windows],
        note=(
            "信号是结构描述（命盘里出现了什么），不是预测；证据强度是证据等级，"
            "不是事件概率。dayun 为 null 表示未提供 gender，此时不算大运。"
        ),
    ).model_dump()


class MultiAnalyzeRequest(BirthRequest):
    """生辰 + 一组主题。主题之间彼此独立，服务端并发执行。"""

    topics: list[str] = Field(
        min_length=1, max_length=MAX_TOPICS,
        description=(
            "要分析的主题，可为中文别名；彼此独立，服务端并发执行。"
            f"至多 {MAX_TOPICS} 个且不得重复 —— 重复主题没有语义作用"
            "（同一主题分析两遍结果相同），只会白占一次并发槽位。"
        ),
        examples=[["事业", "财运", "婚姻"]],
    )

    @field_validator("topics")
    @classmethod
    def _topics_must_be_distinct(cls, value: list[str]) -> list[str]:
        """拒绝重复主题与超长主题名，且每项都受长度上限约束。

        为什么拒绝而不是静默去重：去重之后调用方不会知道自己少问了一个，
        那份「问了两遍」的意图就无声消失了。明确拒绝至少让他知道。

        长度检查放在这里而不是 ``list[str]`` 的项约束上：后者要引入
        ``Annotated`` 与 ``StringConstraints``，为一个二十字的主题名
        付那份可读性代价不值得。列表条数上限已由 ``Field(max_length=...)``
        在 pydantic 层拦住，走不到这里。
        """
        duplicates = sorted({item for item in value if value.count(item) > 1})
        if duplicates:
            raise ValueError(f"主题重复：{'、'.join(duplicates)}")
        overlong = sorted({item for item in value if len(item) > MAX_TOPIC_LENGTH})
        if overlong:
            raise ValueError(
                f"主题名过长（至多{MAX_TOPIC_LENGTH}个字符）："
                + "、".join(item[:MAX_TOPIC_LENGTH] + "…" for item in overlong)
            )
        return value


class TopicAnalysisResponse(BaseModel):
    """一个主题的分析与审查。命盘在响应顶层，这里不重复。"""

    analysis: AnalysisPayload
    critique: dict[str, Any]


class TopicResultResponse(BaseModel):
    """一个主题的结果。失败也是一个结果，``ok=false`` 且 ``error`` 说明原因。"""

    topic: str = Field(description="调用方传入的原始主题，可能是别名")
    topic_name: str = Field(description="解析后的规范主题名")
    ok: bool = Field(description="该主题是否分析成功")
    error: str = Field(description="失败原因；成功时为空字符串")
    analysis: TopicAnalysisResponse | None = Field(
        description="该主题的分析结果；失败时为 null"
    )


class MultiAnalysisResponse(BaseModel):
    chart: dict[str, Any] = Field(description="命盘只算一次，扇出点在它之后")
    topics: list[str]
    results: list[TopicResultResponse]
    succeeded: int
    failed: int


@app.post(
    "/api/analyze/multi",
    summary="多主题并发分析",
    description=(
        "一次请求分析多个主题，服务端**并发**执行。\n\n"
        "主题之间彼此独立、没有跨主题依赖，所以依赖图只有一层。"
        "命盘只算一次 —— 扇出点在它之后，各主题共享同一张不可变命盘。\n\n"
        "**故障隔离**：单个主题失败不影响其余，失败项以 ``ok=false`` 如实带回"
        "原因，而不是让整个请求 500。\n\n"
        "确定性路径下 Python 的 GIL 让线程拿不到 CPU 并行度，所以这里的"
        "并发收益主要是故障隔离与故障定位；注入真 LLM provider 后每个主题"
        "是一次网络调用，线程池这时才真正并行。"
    ),
    tags=["分析"],
    response_model=MultiAnalysisResponse,
    responses=UNPROCESSABLE,
)
def analyze_multi(request: MultiAnalyzeRequest) -> dict[str, Any]:
    try:
        response = service.analyze_multi(
            request.model_dump(exclude={"topics", "true_solar_time"}),
            request.topics,
            true_solar_time=request.true_solar_time,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=_to_user_message(exc)) from exc

    return response.to_dict()


@app.get(
    "/api/topics",
    summary="查询分析主题",
    description=(
        "返回已登记的分析主题及其别名。主题分两层：公共结构层（有规则）与"
        "主题层（如事业、婚姻，**当前一条规则都没有** —— 断语需典籍原文）。"
        "``blocked_by`` 说明主题层为空的原因。"
    ),
    tags=["规则库"],
    response_model=TopicListResponse,
)
def list_topics() -> TopicListResponse:
    return TopicListResponse(
        total=len(TOPICS),
        note="covered = 有专属规则；base_only = 只有公共结构层；unknown = 未登记的主题。",
        topics=[TopicResponse(**topic.to_dict()) for topic in TOPICS],  # type: ignore[arg-type]
    )


class ReportRequest(MultiAnalyzeRequest):
    """导出请求 = 多主题分析请求 + 目标格式。

    复用 ``MultiAnalyzeRequest``：导出的是**同一次分析**，不是另一种
    分析。出生信息与主题的校验规则因此完全一致 —— 导出端点不接受
    分析端点不接受的东西。
    """

    format: Literal["json", "pdf"] = Field(
        default="json",
        description="导出格式：json（结构化存档）或 pdf（排版后的报告）",
    )


@app.post(
    "/api/report",
    summary="导出分析报告",
    description=(
        "把一次多主题分析导出为 JSON 或 PDF。\n\n"
        "**导出不新增判断**：报告里的每个字都是接口已经断言过的东西的"
        "复述 —— 命盘、证据链、强度算式、审查结论、指纹。JSON 与"
        "``/api/analyze/multi`` 的响应逐字段一致（API 视图是它的子集）；"
        "PDF 是同一份内容的排版。\n\n"
        "PDF 用 reportlab 的 CID 字体渲染中文；Content-Disposition 为"
        "attachment，浏览器直接弹下载。"
    ),
    tags=["分析"],
    responses=UNPROCESSABLE,
)
def export_report(request: ReportRequest) -> Response:
    try:
        report = build_report(
            service,
            _birth_fields(request, "topics", "format"),
            request.topics,
            true_solar_time=request.true_solar_time,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=_to_user_message(exc)) from exc

    if request.format == "pdf":
        return Response(
            content=render_pdf(report),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=mingli-report.pdf"},
        )
    return Response(
        content=report_json(report),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=mingli-report.json"},
    )


# ── LLM 提示契约 ──────────────────────────────────────────────────────


@app.get(
    "/api/llm/contract",
    summary="查询 LLM 提示契约",
    description=(
        "返回推理层与大模型之间的契约：系统提示词、输出 JSON Schema、"
        "边界规则、禁用词表与强度披露阈值。\n\n"
        "契约的三层约束：**输入层**只给证据链（不含原始命盘与全量规则库）、"
        "**输出层**只接受 rule_ids 与 text 两个键、**边界层**把越界引用剔除并"
        "记入违约记录。这份契约由假 provider 全量测试覆盖，不依赖外部网络。"
    ),
    tags=["推理"],
    response_model=LLMContractResponse,
)
def get_llm_contract() -> LLMContractResponse:
    return LLMContractResponse(**llm_contract())


# ── 规则库查询 ─────────────────────────────────────────────────────────
# 注意：/api/rules/stats 必须声明在 /api/rules/{rule_id} 之前，
# 否则 "stats" 会被当成规则 ID 吃掉。


@app.get(
    "/api/rules",
    summary="查询规则库",
    description=(
        "按流派、类别、主题、置信等级、来源层级和校核状态过滤规则。"
        "返回的每条规则都带来源、层级与校核状态；"
        "``review_status`` 不是 ACTIVE 的规则不得作为权威引用。"
    ),
    tags=["规则库"],
    response_model=RuleListResponse,
)
def list_rules(
    school: str = Query(default="", max_length=64, description="流派 ID，例如 structural_common"),
    category: str = Query(default="", max_length=64, description="类别，例如 ten_god / pattern / relation"),
    topic: str = Query(default="", max_length=64, description="主题标签"),
    confidence: str = Query(default="", max_length=16, description="LOW / MEDIUM / HIGH"),
    source_tier: SourceTier | None = Query(default=None, description="structural 或 classical"),
    review_status: ReviewStatus | None = Query(default=None, description="校核状态"),
) -> RuleListResponse:
    filters = {
        "school": school,
        "category": category,
        "topic": topic,
        "confidence": confidence,
        "source_tier": str(source_tier) if source_tier else "",
        "review_status": str(review_status) if review_status else "",
    }
    rules = service.registry.select(**filters)
    return RuleListResponse(
        total=len(rules),
        filters={key: value for key, value in filters.items() if value},
        rules=[RuleResponse(**rule.to_dict()) for rule in rules],
    )


@app.get(
    "/api/rules/stats",
    summary="规则库统计",
    description="返回规则总数、生产可用条数，以及按流派、类别、层级、校核状态的分布。",
    tags=["规则库"],
)
def rule_stats() -> dict[str, Any]:
    return service.registry.stats()


@app.get(
    "/api/rules/{rule_id}",
    summary="按 ID 查询单条规则",
    description="返回该规则的完整条件、结论、来源与校核状态；ID 不存在时返回 404。",
    tags=["规则库"],
    response_model=RuleResponse,
    responses=NOT_FOUND,
)
def get_rule(rule_id: str) -> RuleResponse:
    try:
        rule = service.registry.get(rule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知规则：{rule_id}") from exc
    return RuleResponse(**rule.to_dict())


@app.get(
    "/api/schools",
    summary="查询流派",
    description=(
        "返回已注册的流派及其核心方法、代表典籍和已知分歧点。"
        "``classics`` 为空的流派表示没有可引用的公有领域文本，当前不挂任何规则。"
    ),
    tags=["规则库"],
    response_model=SchoolListResponse,
)
def list_schools() -> SchoolListResponse:
    schools = service.schools.select()
    return SchoolListResponse(
        total=len(schools),
        schools=[SchoolResponse(**school.to_dict()) for school in schools],
    )


@app.get(
    "/api/classics/backlog",
    summary="查询典籍层待录入清单",
    description=(
        "返回尚未录入的典籍规则来源，以及每一条被阻塞的具体原因。\n\n"
        "《三命通會》卷八「六甲日甲子時斷」已录入 13 条（含甲辰日七条），"
        "其余典籍条目仍被阻塞在「拿到可核验底本」这一步 —— "
        "没有底本，系统拒绝把任何断语写成经典原文。"
    ),
    tags=["规则库"],
    response_model=BacklogResponse,
)
def classics_backlog() -> BacklogResponse:
    blocked = [entry for entry in CLASSICAL_BACKLOG if entry.status is not BacklogStatus.READY]
    return BacklogResponse(
        total=len(CLASSICAL_BACKLOG),
        blocked=len(blocked),
        next_action=next_action().book,
        entries=[BacklogEntryResponse(**entry.to_dict()) for entry in CLASSICAL_BACKLOG],
    )


# ── Web UI ─────────────────────────────────────────────────────────────
#
# 静态单页，无框架、无构建步骤。挂载放在**所有 API 路由之后**：Starlette
# 按注册顺序匹配，先注册的先生效；挂在前面会让 StaticFiles 抢在路由之前
# 应答，而它对 POST 一律 405。

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", summary="Web UI", include_in_schema=False)
    def index() -> FileResponse:
        """单页界面：输入生辰，看命盘、证据链、审查与流年时间轴。"""
        return FileResponse(STATIC_DIR / "index.html")


# ── 错误消息中文化 ─────────────────────────────────────────────────────
#
# 模块 docstring 承诺「detail 为可直接展示给用户的中文说明」。在此之前，
# pydantic 在请求模型层拦下的错误原样返回英文技术消息的 dict 列表，
# 而引擎（sxtwl）在少数年份上抛出的也是英文。两条路都让承诺落空。
#
# 这里补两件事：把 RequestValidationError 翻成中文，以及给引擎异常包一层
# 中文框架。翻不好的部分不藏 —— 引擎的原始消息保留在中文框架后面，
# 便于排查，也便于 Phase 3.1 修排盘边界时定位。

FIELD_LABELS: dict[str, str] = {
    "year": "公历年",
    "month": "公历月",
    "day": "公历日",
    "hour": "时",
    "minute": "分",
    "longitude": "经度",
    "latitude": "纬度",
    "timezone": "时区",
    "gender": "性别",
    "true_solar_time": "真太阳时",
    "question": "问题",
    "topic": "主题",
    "topics": "主题列表",
    "start_year": "起始年",
    "end_year": "结束年",
    "school": "流派",
    "category": "类别",
    "confidence": "置信等级",
}

#: pydantic 错误类型 → 中文模板。``{label}`` 与 ctx 里的约束值会被填进去。
ERROR_TEMPLATES: dict[str, str] = {
    "missing": "{label}不能为空",
    "none_required": "{label}不能为 null",
    "int_type": "{label}必须是整数",
    "int_parsing": "{label}必须是整数",
    "int_from_float": "{label}必须是整数",
    "bool_type": "{label}必须是true/false",
    "float_type": "{label}必须是数字",
    "float_parsing": "{label}必须是数字",
    "string_type": "{label}必须是字符串",
    "string_too_short": "{label}长度不足（至少{min_length}个字符）",
    "string_too_long": "{label}过长（至多{max_length}个字符）",
    "list_type": "{label}必须是列表",
    "too_short": "{label}项数不足（至少{min_length}项）",
    "too_long": "{label}项数过多（至多{max_length}项）",
    "greater_than_equal": "{label}不能小于{ge}",
    "greater_than": "{label}必须大于{gt}",
    "less_than_equal": "{label}不能大于{le}",
    "less_than": "{label}必须小于{lt}",
    "extra_forbidden": "{label}不是可填的字段",
    "literal_error": "{label}的取值不在允许范围内",
    "value_error": "{label}不合法",
}


def _validation_error_items(exc: RequestValidationError) -> list[tuple[str, str]]:
    """把 pydantic 的错误列表翻成 ``(字段, 中文说明)`` 对。

    三类来源：字段约束（``ge``/``le``/``max_length``）、自定义 validator
    （消息本就是中文，直接采用）、以及没见过的类型 —— 最后一类也不能
    漏成英文，所以兜底模板同样带 ``{label}``。

    Phase 5.2 从「拼一句字符串」改成「产出结构化条目」：前端要逐字段
    渲染错误（五个输入框，用户需要知道错哪个），而 ``detail`` 字符串
    由这些条目拼接而来 —— 两个表示同源，不存在对不上的可能。
    """
    items: list[tuple[str, str]] = []
    for error in exc.errors():
        # 显式转成不定长元组：``ErrorDetails`` 的 ``loc`` 在类型存根里是定长
        # 元组，直接 ``location[-1]`` 会被 mypy 判成越界（它在替我们假设
        # loc 的长度）。转一次就清楚了 —— loc 的长度由 pydantic 决定，
        # 不由类型存根决定。
        location: tuple[object, ...] = tuple(error.get("loc") or ())
        # loc 形如 ("body", "year") 或 ("query", "school")；没有字段名时
        # 说明是整层的问题，用「请求」兜底。
        field = str(location[-1]) if len(location) > 1 else "请求"
        label = FIELD_LABELS.get(field, field)
        kind = str(error.get("type") or "")
        context = dict(error.get("ctx") or {})

        if kind == "value_error":
            # 自定义 validator 写的消息本来就是中文，原样采用。
            # pydantic v2 会给它加 "Value error, " 前缀 —— 那是给开发者看的
            # 错误类型标注，不该出现在给用户的文本里。
            message = str(error.get("msg") or "")
            if message.startswith("Value error, "):
                message = message[len("Value error, "):]
            items.append((field, message or f"{label}不合法"))
            continue

        template = ERROR_TEMPLATES.get(kind)
        if template is None:
            items.append((field, f"{label}不合法（{kind}）"))
            continue
        try:
            items.append((field, template.format(label=label, **context)))
        except (KeyError, IndexError, ValueError):
            # 模板引用了 ctx 里没有的键：宁可少一个数字，也不要抛异常
            # 把 422 变成 500 —— 那是用更糟的方式违反同一条契约。
            items.append((field, f"{label}不合法"))

    # 同一字段可能被多条约束同时报错（例如 missing 与类型错误不会并存，
    # 但保守去重没有代价）：整对相同才去重，消息不同说明约束不同。
    return list(dict.fromkeys(items))


def _translate_validation_errors(exc: RequestValidationError) -> str:
    """把请求模型层的校验失败拼成一句中文说明（``detail`` 的值）。"""
    return "；".join(message for _, message in _validation_error_items(exc)) or "请求不合法"


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求模型层校验失败 → 422 + 中文说明 + 字段级条目。

    没有这个处理器时，FastAPI 返回 ``{"detail": [{loc, msg, type}, ...]}``，
    ``msg`` 是 ``"Input should be greater than or equal to 1"`` 这类英文。
    与模块 docstring 的承诺直接冲突，也让 Web 界面只能显示一串英文。

    Phase 5.2 起响应体多一个 ``fields`` 数组：``[{"field": "month",
    "message": "公历月不能大于12"}]``。``field`` 是**原始字段名**（不是中文
    标签）—— 前端要用它找到对应的输入框；中文在 ``message`` 里。
    ``detail`` 字符串保留：现有消费者与测试依赖它，破坏响应形状是 API
    层的重决策，不属于加一个数组的范围。
    """
    items = _validation_error_items(exc)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "；".join(message for _, message in items) or "请求不合法",
            "fields": [{"field": field, "message": message} for field, message in items],
        },
    )


def _to_user_message(exc: Exception) -> str:
    """把内部异常转成可展示给用户的说明。

    为什么要挑中文：本文件的异常有两个来源，处理方式不同。

    - **我们自己抛的**（``BirthInput`` 的「出生日期时间无效」、``AnalystAgent``
      的「问题不能为空」）—— 本就是中文，原样透传。把它包成「排盘失败：
      问题不能为空」会把问题归错到排盘上。
    - **引擎漏出来的**（sxtwl 在 7 个散落年份上的英文内部错误）—— 最误导的
      一例是 1000 年 6 月 15 日（合法日期）报 ``"day is out of range for
      month"``，用户只会以为自己的日期填错了。这一类必须包一层中文。

    判据是「消息里有没有中文」而不是错误类型：类型在这里区分不了来源
    （两边都是 ``ValueError``）。这个判据是保守的 —— 万一把我们自己的
    中文消息误判成英文，后果只是多一层框架，不会把错误藏起来。

    引擎的原始消息**保留**在中文框架后面：排查时需要它（Phase 3.1 修排盘
    边界要靠它定位），而且隐瞒内部错误比显示它更难查。等 3.1 修好引擎，
    这个函数可以退化成直接透传。
    """
    text = str(exc).strip()
    if not text:
        return f"排盘失败（{type(exc).__name__}）"
    if CJK_SEARCH.search(text):
        return text
    return f"排盘失败：{text}"


def main() -> None:
    """本地启动。``python -m api.server`` 即可，默认 8000 端口。"""
    import uvicorn

    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
