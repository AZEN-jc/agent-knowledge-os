"""MingLi Agent 的本地 FastAPI 入口。

文档：OpenAPI 描述由类型标注与 pydantic 模型自动生成，Swagger UI 在 ``/docs``，
原始描述在 ``/openapi.json``。

错误约定：输入不合法、超出历法库支持范围、或 provider 不可用时一律返回
``422``，``detail`` 为可直接展示给用户的中文说明；不存在的资源返回 ``404``。
不返回 500 堆栈。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from knowledge.classical_backlog import CLASSICAL_BACKLOG, BacklogStatus, next_action
from knowledge.provenance import ReviewStatus, SourceTier
from runtime.mingli_service import MingLiService

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

    year: int = Field(description="公历年", examples=[1990])
    month: int = Field(ge=1, le=12, description="公历月", examples=[6])
    day: int = Field(ge=1, le=31, description="公历日", examples=[15])
    hour: int = Field(ge=0, le=23, description="当地民用时的时", examples=[14])
    minute: int = Field(default=0, ge=0, le=59, description="当地民用时的分", examples=[30])
    longitude: float | None = Field(
        default=None, ge=-180, le=180, description="经度；仅在开启真太阳时校正时需要"
    )
    latitude: float | None = Field(default=None, ge=-90, le=90, description="纬度")
    timezone: str = Field(default="Asia/Shanghai", description="IANA 时区名", examples=["Asia/Shanghai"])
    gender: str | None = Field(
        default=None, description="性别；计算大运顺逆时需要", examples=["男"]
    )


class AnalyzeRequest(BirthRequest):
    """命盘 + 问题。结论必须能追溯到命盘事实与规则，不做确定性预测。"""

    question: str = Field(min_length=1, description="要分析的问题", examples=["事业如何？"])


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


@app.post(
    "/api/chart",
    summary="排盘",
    description="根据出生信息计算四柱、藏干、十神、纳音与四支关系。",
    tags=["排盘"],
    responses=UNPROCESSABLE,
)
def chart(request: BirthRequest) -> dict[str, Any]:
    try:
        response = service.analyze(request.model_dump(), "命盘结构")
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response.chart


@app.post(
    "/api/analyze",
    summary="按问题分析",
    description=(
        "在排盘基础上按问题主题提取事实、匹配规则、形成证据链，"
        "返回事实、匹配规则、证据强度、冲突与审查结果。"
    ),
    tags=["分析"],
    responses=UNPROCESSABLE,
)
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    try:
        response = service.analyze(request.model_dump(exclude={"question"}), request.question)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response.to_dict()


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
    school: str = Query(default="", description="流派 ID，例如 structural_common"),
    category: str = Query(default="", description="类别，例如 ten_god / pattern / relation"),
    topic: str = Query(default="", description="主题标签"),
    confidence: str = Query(default="", description="LOW / MEDIUM / HIGH"),
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
        "返回尚未录入的典籍规则来源，以及每一条被阻塞的具体原因。"
        "当前典籍层一条规则都没有：在拿到可核验的底本之前，"
        "系统拒绝把任何断语写成经典原文。"
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
