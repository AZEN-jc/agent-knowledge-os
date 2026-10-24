"""Web UI 测试。

验收标准是「不开终端也能看到完整推理链」。这里验三件事：

1. 起服务器后 ``GET /`` 拿得到页面，且页面里调用的每个端点都真实存在；
2. 页面不含 ``innerHTML`` 赋值 —— 数据来自 API 与用户输入，
   拼 HTML 字符串等于自己开一个注入口；
3. 真实起一次 uvicorn，走一遍浏览器会走的请求序列。

第 3 条不是冗余：``TestClient`` 走的是 ASGI 直连，不起 socket、不过中间件
栈的某些分支。只有真起服务才能证明「按文档里的命令启动」这件事成立。
"""

import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

from api.server import STATIC_DIR, app

client = TestClient(app)

INDEX = STATIC_DIR / "index.html"
PAGE = INDEX.read_text(encoding="utf-8")


def test_index_is_served_at_the_root():
    response = client.get("/")

    assert response.status_code == 200
    assert "MingLi Agent" in response.text
    assert "text/html" in response.headers["content-type"]


def test_every_endpoint_the_page_calls_actually_exists():
    """页面 fetch 的每个路径都必须在 OpenAPI 里注册过。

    这条守的是「改了 API 路径而页面还在调旧的」。那种错在浏览器里表现为
    404，而没有任何 Python 测试会响 —— 页面不 import 任何东西。
    """
    called = set(re.findall(r'post\("([^"]+)"', PAGE)) | set(re.findall(r'fetch\("([^"]+)"', PAGE))
    assert called, "页面应当至少调用一个接口"

    schema = client.get("/openapi.json").json()
    registered = set(schema["paths"])
    missing = called - registered
    assert not missing, f"页面调用了不存在的端点：{sorted(missing)}"


def test_page_never_assigns_inner_html():
    """不得用 innerHTML 拼装来自 API 或用户输入的文本。

    这不是风格偏好：结论、规则原文、书名都来自语料，生辰来自用户输入。
    把它们拼进 HTML 字符串再赋值 innerHTML，等于自己开一个注入口。

    查的是**赋值**而不是这个词本身 —— 页面注释里就写着「不用 innerHTML」，
    按词查会得到假阳性，而假阳性的测试迟早会被改成永远绿。
    """
    assignments = re.findall(r"\.innerHTML\s*(?:\+?=)", PAGE)
    assert not assignments, f"页面给 innerHTML 赋值了 {len(assignments)} 次"
    assert "textContent" in PAGE, "页面应当用 textContent 写入文本"


def test_page_declares_the_four_things_the_project_promises():
    """README 的承诺是「清晰展示推理过程」，页面必须真的展示这四层。"""
    for marker in ("renderChart", "renderChain", "renderCritique", "renderTimeline"):
        assert marker in PAGE, f"页面缺 {marker}"
    # 出处必须可点开，且带上 noopener —— 那是「可验证」的最后一跳，
    # 也是 tabnabbing 的基本防线。查意图不查变量名：DOM 元素叫什么
    # 无所谓（Phase 5.2 把锚变量从 link 改成 anchor，正是为了不和
    # 证据链循环变量撞名），_blank 与 noopener 的组合必须在场。
    assert re.search(r'target\s*=\s*"_blank"', PAGE)
    assert "noopener noreferrer" in PAGE


def test_static_files_are_mounted_without_shadowing_the_api():
    """静态挂载不能抢在路由前面。

    Starlette 按注册顺序匹配。挂在 API 路由之前时，StaticFiles 会先应答，
    而它对 POST 一律 405 —— 症状是「页面能打开，但一点分析就 405」。
    """
    schema = client.get("/openapi.json").json()
    assert "/api/chart" in schema["paths"]

    response = client.post("/api/chart", json={"year": 1990, "month": 2, "day": 1, "hour": 12})
    assert response.status_code == 200, "静态挂载把 API 路由挡住了"


def test_a_real_server_serves_the_page_and_the_endpoints():
    """真起 uvicorn，走一遍浏览器会走的请求。"""
    repo = Path(__file__).resolve().parent.parent
    process = subprocess.Popen(
        [sys.executable, "-m", "api.server"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = "http://127.0.0.1:8000"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if urllib.request.urlopen(f"{base}/", timeout=2).status == 200:
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.4)
        else:
            raise AssertionError("服务 30 秒内没有就绪")

        with urllib.request.urlopen(f"{base}/", timeout=5) as handle:
            page = handle.read().decode("utf-8")
        assert "MingLi Agent" in page

        body = '{"year":1990,"month":2,"day":1,"hour":12}'
        request = urllib.request.Request(
            f"{base}/api/chart", data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as handle:
            payload = __import__("json").loads(handle.read().decode("utf-8"))
        assert len(payload["pillars"]) == 4
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


# ── 页面读的每个字段都必须在响应里 ─────────────────────────────────────
#
# 上一节守的是「端点存在」，这一节守的是「字段存在」。后者更容易烂：
# 改了响应模型、页面还在读旧字段名，浏览器里表现为一整块空白或
# `undefined`，而 Python 测试一条都不会响 —— 页面不 import 任何东西。
#
# 这两个 bug 都是真的踩过：relations 的形状是 {type, branches, pillars}
# 而页面读 r.pair；liunian 的字段是 stem/branch 而页面读
# heavenly_stem/earthly_branch。两处都不报错，只是渲染出空白。

BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12}


def test_renderchart_fields_exist_in_the_chart_response():
    chart = client.post("/api/chart", json=BIRTH).json()

    for key in ("day_master", "provider", "algorithm_version", "pillars", "relations", "elements"):
        assert key in chart, f"renderChart 读的 {key} 不在 /api/chart 响应里"
    for pillar in chart["pillars"]:
        for key in ("name", "heavenly_stem", "earthly_branch",
                    "hidden_stems", "ten_god", "na_yin"):
            assert key in pillar, f"renderChart 读的 pillar.{key} 不在响应里"
    for relation in chart["relations"]:
        for key in ("type", "branches", "pillars"):
            assert key in relation, f"renderChart 读的 relation.{key} 不在响应里"


def test_renderchain_fields_exist_in_the_analysis_response():
    body = client.post(
        "/api/analyze/multi", json={**BIRTH, "topics": ["事业", "财运"]}
    ).json()
    result = body["results"][0]
    evidence = result["analysis"]["analysis"]["evidence"]

    for key in ("topic_name", "status", "coverage_note", "chain", "strength",
                "strength_breakdown", "untraced_rules", "unreviewed_rules"):
        assert key in evidence, f"renderChain 读的 evidence.{key} 不在响应里"
    for key in ("supporting_rules", "raw_support", "saturation_k"):
        assert key in evidence["strength_breakdown"], f"strength_breakdown 缺 {key}"

    link = evidence["chain"][0]
    for key in ("rule_id", "conclusion", "confidence", "source_tier",
                "review_status", "is_production_ready", "urn", "citation", "conditions"):
        assert key in link, f"renderChain 读的 chain.{key} 不在响应里"
    condition = link["conditions"][0]
    for key in ("key", "expected", "actual", "sources"):
        assert key in condition, f"renderCondition 读的 condition.{key} 不在响应里"

    for key in ("passed", "issues"):
        assert key in result["analysis"]["critique"], f"renderCritique 读的 {key} 不在响应里"


def test_rendertimeline_fields_exist_in_the_timeline_response():
    body = client.post(
        "/api/timeline",
        json={**BIRTH, "gender": "男", "start_year": 2024, "end_year": 2026, "topic": "财运"},
    ).json()

    for key in ("note", "windows"):
        assert key in body, f"renderTimeline 读的 {key} 不在响应里"
    window = body["windows"][0]
    for key in ("liunian", "dayun", "signals", "strength", "report"):
        assert key in window, f"renderTimeline 读的 window.{key} 不在响应里"
    for key in ("stem", "branch"):
        assert key in window["liunian"], f"renderTimeline 读的 liunian.{key} 不在响应里"
    for signal in window["signals"]:
        for key in ("label", "detail"):
            assert key in signal, f"renderTimeline 读的 signal.{key} 不在响应里"


def test_the_relations_line_would_actually_render():
    """地支关系不能是空的 —— 上面那个 r.pair 的 bug 就是这个症状。

    这张盘（1990-02-01 12:00，四支巳丑酉午）确实有六害丑午，
    所以页面那一行必须能渲染出内容来。
    """
    chart = client.post("/api/chart", json=BIRTH).json()

    assert chart["relations"], "该命盘应有地支关系"
    rendered = "；".join(
        f"{r['type']}：{''.join(r['branches'])}（{'+'.join(r['pillars'])}）"
        for r in chart["relations"]
    )
    assert "六害" in rendered
    assert "丑" in rendered and "午" in rendered
