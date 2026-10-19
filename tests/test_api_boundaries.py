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

    边界值 2 与 9997 是**策略选择**（全路径可用区间），不是引擎上限 ——
    Phase 3.1 修好历法换算后引擎已支持 1–9999，两端各有一个窄窗口走不通，
    详见 :func:`test_year_bounds_match_the_engine` 的说明。

    第一版这里写的是 1 与 9999，两头都错：year=1 与 year=9999 本身就是
    失败年（引擎内部 +1 后越界，9998 也挂）。是「边界内年份应可用」
    那条测试逮到的。
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


def test_formerly_broken_engine_years_now_work():
    """引擎修好的 6 个年份，对外必须返回 200 而不是中文框架包着的错误。

    这 6 年（899–901、999–1001）此前是 **Phase 2 记录在案的缺陷**：
    sxtwl 对 1582 年前返回儒略历，900 与 1000 在儒略历是闰年，
    于是给出 2 月 29 日；公历里这两年都不是闰年，``datetime(900, 2, 29)``
    直接抛 ``ValueError: day is out of range for month``，而 API 只能用
    「排盘失败：…」包一层中文。

    Phase 3.1 修了根因（改走 :func:`engines.bazi.jieqi._jd_to_gregorian`），
    所以这条测试从「钉住缺陷」翻成「验收修复」。

    **这条测试以前叫** ``test_engine_failure_years_get_a_chinese_framed_error``，
    断言的是这 6 年返回 422 + 中文框架。修好之后它如预期变红 —— 那正是
    「已知缺陷的闹钟」该有的行为。现在改为断言 200。
    """
    for year in (899, 900, 901, 999, 1000, 1001):
        response = client.post("/api/chart", json={**BIRTH, "year": year})
        assert response.status_code == 200, (
            f"year={year} 应已修复，实得 {response.status_code}："
            f"{response.text[:120]}"
        )
        assert response.json()["pillars"], f"year={year} 应排出四柱"


def test_the_fix_is_verified_against_an_independent_calendar_baseline():
    """修复的可信度来自独立基准，不是「跑通了」。

    真正的验证在 ``tests/test_jieqi_calendar.py``：把我们的公历换算与
    sxtwl 的儒略标签之差，逐项对上**史料上的儒略→公历修正量表**
    （1582 年 +10 天、1500 年 +9 天、…、1583 年起 0 天）。
    那条基准不依赖本项目的任何一行代码。

    这里只做接口层的最小确认：修好之后，同一个儒略日经两条路换算
    必须落在同一个绝对时刻上。
    """
    import datetime as dt

    import sxtwl

    from engines.bazi.jieqi import _jd_to_gregorian

    entry = sxtwl.getJieQiByYear(1500)[0]  # 立春，修正量 +9 天
    julian = sxtwl.JD2DD(entry.jd)
    gregorian = _jd_to_gregorian(entry.jd)

    julian_instant = dt.datetime(
        int(julian.Y), int(julian.M), int(julian.D),
        int(julian.h), int(julian.m), int(julian.s),
    )
    gregorian_instant = dt.datetime(
        gregorian[0], gregorian[1], gregorian[2], gregorian[3], gregorian[4], gregorian[5]
    )
    # 同一个儒略日：两个标签必须相差正好 9 天（1500 年的修正量）。
    assert (gregorian_instant - julian_instant).days == 9


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
    """``year`` 的 ``ge=2, le=9997`` 是**策略边界**，等于引擎全路径可用区间。

    Phase 3.1 修好节气历法换算之后，引擎实际已支持 1–9999 年（此前 899–901
    与 999–1001 共 6 年会崩）。但区间两端各有一个**窄窗口**走不通：

    - **第 1 年小寒之前**（约 1 月 5 日前）：前一个「节」落在第 0 年，
      ``datetime`` 表示不了，报 `找不到 … 之前的节气`。
    - **第 9999 年小寒之后**（9999-12-31 21:14 后）：后一个「节」落在第 10000
      年，同上。只影响需要「之后」的路径（大运起运年龄），排盘本身不受影响。

    这两个窗口是**日期相关**的，没法用 ``ge``/``le`` 表达。所以这里取
    「每一条路径都能走通」的区间作为公开契约，而不是引擎的理论上限。

    若哪天要放宽，先看清楚这两个窗口的报错是否可接受 —— 目前它们是清晰的中文
    说明，见 :func:`test_boundary_windows_fail_with_a_readable_reason`。
    """
    for year, expected in ((2, 200), (9997, 200), (1, 422), (9998, 422), (9999, 422)):
        response = client.post("/api/chart", json={**BIRTH, "year": year})
        assert response.status_code == expected, (
            f"year={year} 应为 {expected}，实得 {response.status_code}："
            f"{response.text[:100]}"
        )


def test_boundary_windows_fail_with_a_readable_reason():
    """策略边界外的窄窗口，报错必须说清原因而不是英文内部错误。

    这两个窗口放不进 ``ge``/``le``（日期相关），所以一旦有人放宽边界，
    这两条就是安全网：它们确认失败时给出的是人能读懂的中文。
    """
    # 第 1 年小寒之前：前一个节在第 0 年。
    response = client.post("/api/chart", json={**BIRTH, "year": 1, "month": 1, "day": 1})
    assert response.status_code == 422  # 被 ge=2 拦在模型层
    assert "公历年不能小于2" in response.json()["detail"]

    # 放开边界后的真实表现（绕过模型层，直接打服务层）。
    from runtime.mingli_service import MingLiService

    service = MingLiService()
    try:
        service.analyze({"year": 1, "month": 1, "day": 1, "hour": 12}, "事业")
    except RuntimeError as exc:
        assert "之前的节气" in str(exc), f"报错不可读：{exc}"
    else:
        raise AssertionError("第 1 年小寒之前应当报错")


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
