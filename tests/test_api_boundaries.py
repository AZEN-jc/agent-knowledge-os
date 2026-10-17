"""API 边界输入用例：把「当前行为」与「文档契约」的差距钉成可执行的清单。

## 为什么有这个文件

`api/server.py` 的模块 docstring 写着：

> 错误约定：输入不合法、超出历法库支持范围、或 provider 不可用时一律返回 422，
> ``detail`` 为**可直接展示给用户的中文说明**。

实测下来，**状态码这一半成立，`detail` 那一半不成立**：pydantic 在请求模型层
拦下的错误，`detail` 是原始的英文技术消息（一个 dict 列表），既不是中文，
也不是能直接给用户看的东西。

## 两类测试

- **绿的**：钉住「越界输入必须被拒」。这是当前真实行为，改了要立刻知道。
- **``xfail(strict=True)``**：钉住「``detail`` 必须是中文说明」这条契约。
  它当前不成立，所以标成预期失败 —— **不是伪造通过**：pytest 会把它们报成
  ``xfailed``（跑过、按预期失败），而不是 ``passed``。

  ``strict=True`` 是关键：**谁把消息改好了，这些测试会立刻变成 XPASS 并报错**，
  逼他回来更新这份清单。没有 strict，修好了也不会有人知道。

## 修法（本阶段不实施，见审计报告 §7）

给请求模型加约束与中文消息，让校验在 pydantic 层就产出可展示的文本，例如
``year: int = Field(ge=1, le=9999, description=...)`` 配合自定义 validator；
或统一在异常处理器里把 ``RequestValidationError`` 转成中文说明。
两条都改的是 `api/server.py` 的请求模型层，**不动排盘、规则、证据与公开响应契约**。
"""

import re

import pytest
from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)

CJK = re.compile(r"[\u4e00-\u9fff]")

BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}

# (标签, 请求体, 端点)
# 这些输入全部应当被拒 —— 差异只在「拒绝时说了什么」。
BOUNDARY_INPUTS = (
    ("year=0",          {**BIRTH, "year": 0},          "/api/chart"),
    ("year=-1",         {**BIRTH, "year": -1},         "/api/chart"),
    ("year=10000",      {**BIRTH, "year": 10000},      "/api/chart"),
    ("year=999999999",  {**BIRTH, "year": 999999999},  "/api/chart"),
    ("month=0",         {**BIRTH, "month": 0},         "/api/chart"),
    ("month=13",        {**BIRTH, "month": 13},        "/api/chart"),
    ("day=0",           {**BIRTH, "day": 0},           "/api/chart"),
    ("day=32",          {**BIRTH, "day": 32},          "/api/chart"),
    ("hour=-1",         {**BIRTH, "hour": -1},         "/api/chart"),
    ("hour=24",         {**BIRTH, "hour": 24},         "/api/chart"),
    ("minute=60",       {**BIRTH, "minute": 60},       "/api/chart"),
    ("longitude=181",   {**BIRTH, "longitude": 181},   "/api/chart"),
    ("question=空串",    {**BIRTH, "question": ""},     "/api/analyze"),
    ("question=纯空格",  {**BIRTH, "question": "   "},  "/api/analyze"),
    ("question=制表换行", {**BIRTH, "question": "\t\n"}, "/api/analyze"),
    # gender 走 /api/chart：/api/analyze 还要求 question，缺它的话
    # 先报的是「question 缺失」，测不到 gender 的校验。
    ("gender=未知值",    {**BIRTH, "gender": "其他"},   "/api/chart"),
)


# ── 绿的：越界必须被拒 ────────────────────────────────────────────────


def test_every_boundary_input_is_rejected():
    """所有越界输入返回 422，且不返回 500 堆栈。

    这一条当前成立，是本文件的地基：如果哪天某个参数**不再**被拒，
    说明校验被放松了，而不是消息被改好了。
    """
    for label, body, path in BOUNDARY_INPUTS:
        response = client.post(path, json=body)
        assert response.status_code == 422, (
            f"{label} 应被拒（422），实得 {response.status_code}：{response.text[:120]}"
        )


def test_rejection_never_leaks_a_server_error():
    """拒绝时不能抛 500，也不能把 traceback 当 detail 返回。"""
    for label, body, path in BOUNDARY_INPUTS:
        response = client.post(path, json=body)
        assert response.status_code < 500, f"{label} 触发了服务端错误"
        assert "Traceback" not in response.text, f"{label} 的响应里带 traceback"


def test_conforming_inputs_are_not_rejected():
    """合法输入不能被误拒 —— 收边界时最容易顺手收过头。"""
    assert client.post("/api/chart", json=BIRTH).status_code == 200
    assert client.post(
        "/api/analyze", json={**BIRTH, "question": "事业"}
    ).status_code == 200


def test_the_two_boundary_checks_that_already_conform():
    """这两条当前就符合契约，单独钉住，免得被上面那条 xfail 一起带走。

    ``gender`` 走 ``/api/chart``：``/api/analyze`` 还要求 ``question``，
    缺它的话先报的是「question 缺失」，测不到 gender 的校验。
    """
    blank = client.post("/api/analyze", json={**BIRTH, "question": "   "}).json()
    assert isinstance(blank["detail"], str)
    assert "问题不能为空" in blank["detail"]

    gender = client.post("/api/chart", json={**BIRTH, "gender": "其他"}).json()
    assert isinstance(gender["detail"], str)
    assert CJK.search(gender["detail"])


# ── xfail：detail 必须是中文说明（当前不成立）────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="契约要求 detail 为可直接展示的中文说明；pydantic 层错误当前是英文技术消息。",
)
def test_error_detail_is_always_a_chinese_string():
    """契约：``detail`` 是可展示的中文说明。

    当前 pydantic 在请求模型层拦下的错误返回一个 dict 列表（英文技术消息），
    与文档契约不符。修好后这条会 XPASS，strict 会把它报成失败，
    提醒维护者删掉 xfail 并更新本文件的说明。
    """
    offenders = []
    for label, body, path in BOUNDARY_INPUTS:
        detail = client.post(path, json=body).json().get("detail")
        if not isinstance(detail, str) or not CJK.search(detail):
            offenders.append(f"{label}: {detail!r}")

    assert not offenders, (
        "以下输入的 detail 不是中文说明：\n  " + "\n  ".join(offenders)
    )


@pytest.mark.xfail(
    strict=True,
    reason="year 字段未声明 ge/le，越界由 datetime() 抛出后再包装，消息混了英文内部信息。",
)
def test_year_is_constrained_at_the_request_model():
    """``year`` 应在请求模型上就有边界，而不是留给 ``datetime()`` 抛。

    当前 ``BirthRequest.year`` 是裸的 ``int``（无 ``ge`` / ``le``），
    越界时错误从 ``BirthInput.__post_init__`` 的 ``datetime()`` 冒出，
    消息形如「出生日期时间无效：year 0 is out of range」—— 中文前缀接英文内部信息。
    """
    from api.server import BirthRequest

    field = BirthRequest.model_fields["year"]
    assert field.metadata, "year 上没有任何约束元数据（ge/le）"


def test_question_strips_whitespace_at_the_request_model():
    """``question`` 应在请求模型上就 strip，而不是让纯空格穿到服务层。

    这条**当前成立**（服务层会拦），但它拦得比契约要求晚一层：
    API 的 ``min_length=1`` 放行 ``"   "``，由 `AnalystAgent` 抛错再转 422。
    放在这里是为了记录当前边界的确切位置。
    """
    response = client.post("/api/analyze", json={**BIRTH, "question": "   "})

    assert response.status_code == 422
    assert "问题不能为空" in response.json()["detail"]
