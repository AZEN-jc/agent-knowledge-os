"""API 边界输入用例：把「文档契约」钉成可执行的清单。

## 为什么有这个文件

`api/server.py` 的模块 docstring 写着：

> 错误约定：输入不合法、超出历法库支持范围、或 provider 不可用时一律返回 422，
> ``detail`` 为**可直接展示给用户的中文说明**。

2026-10-17 之前这条只成立了一半：状态码一直对，``detail`` 在 pydantic 层
是英文技术消息的 dict 列表。本轮（Phase 2.3）加了
:func:`api.server.on_validation_error` 与一系列字段约束，两条 xfail 随之转正。

## 现在这个文件守三件事

1. **越界必须被拒**（422，不 500，不带 traceback）；
2. **拒绝时说的是中文**，且不带 pydantic 的 ``Value error, `` 前缀；
3. **治理项生效**：主题数、重复主题、主题名长度、时间轴跨度、文本长度
   各有上限，且上限不被顺手收窄到误拒合法输入。

## 已修复的历史

- ``test_error_detail_is_always_a_chinese_string`` 与
  ``test_year_is_constrained_at_the_request_model`` 曾是
  ``xfail(strict=True)``。strict 的设计起效了：修好后它们变成 XPASS 并报错，
  逼维护者回来删标记 —— 这正是当初写 strict 的目的。
"""

import re

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


# ── 曾经是 xfail，现已修复并转正 ─────────────────────────────────────


def test_error_detail_is_always_a_chinese_string():
    """契约：``detail`` 是可展示的中文说明。

    这条**曾经是** ``xfail(strict=True)``：pydantic 在请求模型层拦下的错误
    返回一个 dict 列表，``msg`` 是 ``"Input should be greater than or
    equal to 1"`` 这类英文。2026-10-17 加了
    :func:`api.server.on_validation_error` 之后修好，标记随之删除。

    保留这条而不是删掉：它现在是「错误消息契约」的唯一守卫。谁把处理器
    删了、或新加一个绕过它的端点，这条会立刻红。
    """
    offenders = []
    for label, body, path in BOUNDARY_INPUTS:
        detail = client.post(path, json=body).json().get("detail")
        if not isinstance(detail, str) or not CJK.search(detail):
            offenders.append(f"{label}: {detail!r}")

    assert not offenders, (
        "以下输入的 detail 不是中文说明：\n  " + "\n  ".join(offenders)
    )


def test_year_is_constrained_at_the_request_model():
    """``year`` 在请求模型上就有边界，而不是留给 ``datetime()`` 抛。

    加了 ``ge=2, le=9997`` 之后，越界在 pydantic 层就被拦下，消息是
    「公历年不能大于9997」而不是「出生日期时间无效：year 10000 is out of
    range」那种中文前缀接英文内部信息的混合体。

    边界值 2 与 9997 是**扫出来的**，不是按常识填的：引擎在 year=1 与
    year=9998/9999 上都会失败。第一版这里写的是 1 与 9999，两头都错。
    """
    from api.server import BirthRequest

    field = BirthRequest.model_fields["year"]
    assert field.metadata, "year 上没有任何约束元数据（ge/le）"
    # 边界值本身：允许 2 与 9997，拒绝 1 / 9998 / 9999。
    for good in (2, 9997):
        BirthRequest.model_validate(
            {"year": good, "month": 6, "day": 15, "hour": 12}
        )
    for bad in (1, 9998, 9999):
        try:
            BirthRequest.model_validate({"year": bad, "month": 6, "day": 15, "hour": 12})
        except Exception:
            continue
        raise AssertionError(f"year={bad} 应当被请求模型拒绝")


def test_question_strips_whitespace_at_the_request_model():
    """``question`` 应在请求模型上就 strip，而不是让纯空格穿到服务层。

    这条**当前成立**（服务层会拦），但它拦得比契约要求晚一层：
    API 的 ``min_length=1`` 放行 ``"   "``，由 `AnalystAgent` 抛错再转 422。
    放在这里是为了记录当前边界的确切位置。
    """
    response = client.post("/api/analyze", json={**BIRTH, "question": "   "})

    assert response.status_code == 422
    assert "问题不能为空" in response.json()["detail"]


# ── Phase 2.3 新增治理项 ──────────────────────────────────────────────


def test_topic_count_is_capped():
    """主题条数有上限，超过即拒。

    上限的意义是给线程池一个硬顶：``analyze_multi`` 用
    ``max_workers=len(topics)``，没有上限时一次请求就能开出任意多个线程。
    """
    from api.server import MAX_TOPICS

    ok = ["事业", "财运", "婚姻", "健康", "命局", "结构", "紫微", "流年"]
    assert len(ok) == MAX_TOPICS
    assert client.post("/api/analyze/multi", json={**BIRTH, "topics": ok}).status_code == 200

    over = client.post("/api/analyze/multi", json={**BIRTH, "topics": [*ok, " extra "]})
    assert over.status_code == 422
    assert str(MAX_TOPICS) in over.json()["detail"]


def test_duplicate_topics_are_rejected_not_silently_deduped():
    """重复主题明确拒绝。

    静默去重会让调用方不知道自已少问了一个；明确拒绝至少让他知道。
    注意这条测的是**拒绝**，不是去重后的条数。
    """
    response = client.post("/api/analyze/multi", json={**BIRTH, "topics": ["事业", "事业"]})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "重复" in detail
    # 不带 pydantic 的 "Value error, " 前缀 —— 那是给开发者看的类型标注。
    assert not detail.startswith("Value error"), detail


def test_topic_item_length_is_bounded():
    """主题名有长度上限，超长主题名不会走到解析层。"""
    from api.server import MAX_TOPIC_LENGTH

    ok = "事业" * (MAX_TOPIC_LENGTH // 2)
    assert client.post(
        "/api/analyze/multi", json={**BIRTH, "topics": [ok]}
    ).status_code == 200

    over = client.post("/api/analyze/multi", json={**BIRTH, "topics": ["事业" * 20]})
    assert over.status_code == 422
    assert "过长" in over.json()["detail"]


def test_timeline_span_is_bounded():
    """时间轴起止年份相差有上限，正好等于上限时放行。"""
    from api.server import MAX_TIMELINE_SPAN

    boundary = {**BIRTH, "start_year": 2024, "end_year": 2024 + MAX_TIMELINE_SPAN}
    assert client.post("/api/timeline", json=boundary).status_code == 200

    over = {**BIRTH, "start_year": 2024, "end_year": 2024 + MAX_TIMELINE_SPAN + 1}
    response = client.post("/api/timeline", json=over)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "相差" in detail and "分段" in detail


def test_question_length_is_bounded():
    """问题文本有上限；没有上限时一个超大字符串会一路走到证据层。"""
    from api.server import MAX_QUESTION_LENGTH

    ok = {**BIRTH, "question": "事业" * (MAX_QUESTION_LENGTH // 2)}
    assert client.post("/api/analyze", json=ok).status_code == 200

    over = {**BIRTH, "question": "x" * (MAX_QUESTION_LENGTH + 1)}
    response = client.post("/api/analyze", json=over)
    assert response.status_code == 422
    assert "过长" in response.json()["detail"]


def test_engine_failure_years_get_a_chinese_framed_error():
    """引擎在 6 个夹在区间中部的年份上抛英文，API 必须包一层中文。

    这 6 年（899–901 与 999–1001）是 **Phase 3.1 的待修缺陷**，本测试不假装
    它不存在，只钉住「对外不出现裸英文」这一条。最误导的一例：1000 年
    2 月 1 日（合法日期）报 ``"day is out of range for month"``，
    用户只会以为自已的日期填错了。

    边界上的 1 / 9998 / 9999 不在这里测 —— 它们已被 ``ge=2, le=9997``
    在请求模型层拦掉，见 :func:`test_year_bounds_match_the_engine`。
    """
    from api.server import ENGINE_FAILURE_YEARS

    assert ENGINE_FAILURE_YEARS == (899, 900, 901, 999, 1000, 1001)
    for year in ENGINE_FAILURE_YEARS:
        response = client.post("/api/chart", json={**BIRTH, "year": year})

        assert response.status_code == 422, f"year={year} 应被拒"
        detail = response.json()["detail"]
        assert CJK.search(detail), f"year={year} 的 detail 不是中文：{detail!r}"
        assert "排盘失败" in detail, f"year={year} 的 detail 缺中文框架：{detail!r}"
        # 引擎原文保留在框架后面 —— 排查需要它，隐瞒比显示更难查。
        assert "排盘失败：" in detail


def test_valid_years_inside_the_supported_range_still_work():
    """治理不能顺手收窄可用范围。

    上一节那 7 个失败年夹在 2–9999 之间，很容易被「一刀切」成
    ``ge=1002`` 之类的粗暴区间。这里钉住边界内的大量年份照旧可用。
    """
    for year in (2, 100, 500, 898, 902, 998, 1002, 1024, 1583, 1900, 1990,
                 2024, 2100, 9997):
        response = client.post("/api/chart", json={**BIRTH, "year": year})
        assert response.status_code == 200, f"year={year} 应可用，实得 {response.status_code}"


def test_year_bounds_match_the_engine():
    """``year`` 的 ge/le 必须等于引擎实测的可用边界。

    这条钉的是**上一轮犯过的错**：第一版写的是 ``ge=1, le=9999``，两头都错 ——
    year=1 与 year=9999 本身就是失败年（引擎内部 +1 后越界，9998 也挂）。
    是「边界内年份应可用」那条测出来的：9999 返回 422。
    """
    for year, expected in ((2, 200), (9997, 200), (1, 422), (9998, 422), (9999, 422)):
        response = client.post("/api/chart", json={**BIRTH, "year": year})
        assert response.status_code == expected, (
            f"year={year} 应为 {expected}，实得 {response.status_code}："
            f"{response.text[:100]}"
        )


def test_blank_topic_fails_as_a_topic_not_as_a_request():
    """空白主题名按**故障隔离**处理，不是整个请求失败。

    这是刻意的设计，不是漏拦：``/api/analyze/multi`` 的契约是「单个主题失败
    不影响其余，失败项以 ok=false 如实带回原因」。空白主题走的是这条路 ——
    请求 200，那一项 ok=false 且 error 是中文说明。

    第一版这条测试断言 422，是我读错了契约。改成断言真实契约，并把
    「为什么不是 422」写在这里，免得下一个人再改错方向。
    """
    response = client.post("/api/analyze/multi", json={**BIRTH, "topics": [""]})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert result["analysis"] is None
    assert result["error"], "失败项必须带回原因"
    assert CJK.search(result["error"]), f"失败原因不是中文：{result['error']!r}"
