"""MingLi Agent 的本地 FastAPI 入口。

文档：OpenAPI 描述由类型标注与 pydantic 模型自动生成，Swagger UI 在 ``/docs``，
原始描述在 ``/openapi.json``。

错误约定：输入不合法、超出历法库支持范围、或 provider 不可用时一律返回
``422``，``detail`` 为可直接展示给用户的中文说明；不返回 500 堆栈。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from runtime.mingli_service import MingLiService

UNPROCESSABLE: dict[int | str, dict[str, Any]] = {
    422: {
        "description": "出生信息非法、超出历法库支持范围，或排盘 provider 不可用。",
    }
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
