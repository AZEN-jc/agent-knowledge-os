"""前端契约测试：static/index.html 与真实 API 响应的逐字段对账（Phase 5.2）。

## 这个文件守什么

前端是**没有编译器的那一半**。JS 里读 ``chart.pillars`` 不会因为后端把它
改名成 ``four_pillars`` 而报错 —— 它只会静默返回 undefined，然后渲染出一行
空白。本项目已经栽过同一个坑：UI 曾读 ``chart.elements.missing``，而
provider 从来没产出过这个键，「缺五行」一行从上线起就是死的
（Phase 5.2 已删掉那行死代码，五行普查归 5.3）。

所以把「前端读的每条路径」变成可执行的契约，两头盯：

1. **后端漂移**：``RESPONSE_CONTRACT`` 里每条声明的路径，必须能在真实
   API 响应里解析到。后端改名、挪位、删字段，这里红。
2. **前端漂移**：静态提取 index.html 里 JS 实际读取的属性路径（经别名
   归一化），必须是 ``RESPONSE_CONTRACT`` 声明集合的子集。前端改出一个
   新读法（改错字段名、读不存在的层级），这里红 —— 想加新读法，先
   consciously 更新契约。

请求方向同样对账：前端发的字段必须是 BirthRequest 的合法属性且覆盖其
必填项；发的路径必须是已注册的端点。``extra="forbid"`` 之下，多发一个
字段就是一次 422，这种错也该在测试里死，不在用户手里死。

## 方法说明

没有引入 JS 运行时（node/jsdom 都不在依赖里，也不该为一个测试进生产
依赖）。提取靠针对本文件写法的正则，三件事保证它无歧义：

- **剥注释**：注释里提到的字段名不是读取（死代码的教训就留在注释里）；
- **方法调用不是字段**：``.some(`` / ``.map(`` / ``.toFixed(`` 之后的
  段不捕获（负向先行断言）；
- **别名归一化**：渲染函数的参数与循环变量是别名（``first`` 实际是
  ``results[]``、``link`` 实际是证据链的一环），``ALIASES`` 表把别名
  翻译回真实响应路径。JS 里因此避开了同名歧义 —— DOM 锚元素叫 anchor
  不叫 link，这条约束由 test_dom_variables_never_shadow_data_roots 钉住。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from api.server import app

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "static" / "index.html"

client = TestClient(app)

# ── 样本请求：覆盖 UI 读取的每一类响应结构 ────────────────────────────
#
# 三张命盘各司其职，选错任何一张都会让下面的契约空转：
#
# - 1990-06-15 12:00：四柱 庚午/戊寅/甲子/丙寅（近似），午午自刑 ——
#   relations 非空，地支关系那一行有数据可验。
# - 1990-02-28 00:00：四柱 庚午/戊寅/甲子/甲子 —— 日柱甲子 + 时柱甲子，
#   命中《三命通會》卷八六甲日甲子时断，chain 里有一条带 urn 与完整
#   citation 的典籍层规则。没有它，citation.* 与 urn 全部空测。
# - 时间轴带 gender：dayun 非 null。缺 gender 时 dayun 恒 null，
#   dayun.* 两条路径会空转。
CHART_BIRTH = {"year": 1990, "month": 6, "day": 15, "hour": 12}
CLASSICAL_BIRTH = {"year": 1990, "month": 2, "day": 28, "hour": 0}

SAMPLES: list[tuple[str, dict[str, object]]] = [
    ("/api/chart", dict(CHART_BIRTH)),
    ("/api/analyze/multi", {**CLASSICAL_BIRTH, "topics": ["命局"]}),
    (
        "/api/timeline",
        {**CHART_BIRTH, "gender": "男", "start_year": 2024, "end_year": 2026},
    ),
    # 422 样本：模型层校验失败的响应体（detail + fields）。
    ("/api/chart", {**CHART_BIRTH, "month": 13}),
]

# ── 响应契约：前端被允许读取的每一条路径 ──────────────────────────────
#
# 路径是**端点相对的**（``payload.`` 之类的前缀不存在于真实响应里，
# 它只是 JS 的变量名）。记号：``a.b`` 对象属性；``a[]`` 列表元素；
# ``a[].b`` 列表元素的属性。可空字段（urn/citation/dayun）的**子路径**
# 要求样本里至少有一个非空实例 —— 样本选型就是在保证这件事，见
# SAMPLES 上面的注释。
RESPONSE_CONTRACT: frozenset[str] = frozenset({
    # 命盘（/api/chart 的响应本体；/api/analyze/multi 的 chart 子键同形）
    "day_master",
    "provider",
    "algorithm_version",
    "pillars",
    "pillars[].name",
    "pillars[].heavenly_stem",
    "pillars[].earthly_branch",
    "pillars[].hidden_stems",
    "pillars[].ten_god",
    "pillars[].na_yin",
    "relations",
    "relations[].type",
    "relations[].branches",
    "relations[].pillars",
    # 五行普查（Phase 5.3：provider 随命盘产出，与事实层同源）
    "elements",
    "elements.count",
    "elements.missing",
    "elements.dominant",
    # 多主题分析（/api/analyze/multi）
    "chart",
    "results",
    "results[].ok",
    "results[].topic",
    "results[].error",
    "results[].analysis",
    "results[].analysis.analysis",
    "results[].analysis.analysis.evidence",
    "results[].analysis.analysis.evidence.topic_name",
    "results[].analysis.analysis.evidence.status",
    "results[].analysis.analysis.evidence.coverage_note",
    "results[].analysis.analysis.evidence.untraced_rules",
    "results[].analysis.analysis.evidence.unreviewed_rules",
    "results[].analysis.analysis.evidence.strength",
    "results[].analysis.analysis.evidence.strength_breakdown",
    "results[].analysis.analysis.evidence.strength_breakdown.supporting_rules",
    "results[].analysis.analysis.evidence.strength_breakdown.raw_support",
    "results[].analysis.analysis.evidence.strength_breakdown.saturation_k",
    "results[].analysis.analysis.evidence.chain",
    "results[].analysis.analysis.evidence.chain[].rule_id",
    "results[].analysis.analysis.evidence.chain[].conclusion",
    "results[].analysis.analysis.evidence.chain[].confidence",
    "results[].analysis.analysis.evidence.chain[].source_tier",
    "results[].analysis.analysis.evidence.chain[].review_status",
    "results[].analysis.analysis.evidence.chain[].is_production_ready",
    "results[].analysis.analysis.evidence.chain[].urn",
    "results[].analysis.analysis.evidence.chain[].citation",
    "results[].analysis.analysis.evidence.chain[].citation.book",
    "results[].analysis.analysis.evidence.chain[].citation.edition",
    "results[].analysis.analysis.evidence.chain[].citation.chapter",
    "results[].analysis.analysis.evidence.chain[].citation.original_text",
    "results[].analysis.analysis.evidence.chain[].citation.url",
    "results[].analysis.analysis.evidence.chain[].conditions",
    "results[].analysis.analysis.evidence.chain[].conditions[].key",
    "results[].analysis.analysis.evidence.chain[].conditions[].expected",
    "results[].analysis.analysis.evidence.chain[].conditions[].actual",
    "results[].analysis.analysis.evidence.chain[].conditions[].sources",
    "results[].analysis.critique",
    "results[].analysis.critique.passed",
    "results[].analysis.critique.issues",
    # 流年时间轴（/api/timeline）
    "note",
    "windows",
    "windows[].liunian",
    "windows[].liunian.stem",
    "windows[].liunian.branch",
    "windows[].strength",
    "windows[].dayun",
    "windows[].dayun.heavenly_stem",
    "windows[].dayun.earthly_branch",
    "windows[].report",
    "windows[].signals",
    "windows[].signals[].label",
    "windows[].signals[].detail",
    # 422 响应体（请求模型层校验失败）
    "detail",
    "fields",
    "fields[].field",
    "fields[].message",
})

#: JS 里可能承载 API 数据的根变量名。属性提取只锚定这些名字 —— DOM
#: 属性（node.className、input.checked、anchor.href）因此天然落在集合外。
DATA_ROOTS = (
    "chart", "payload", "data", "evidence", "critique", "window", "signal",
    "link", "condition", "citation", "pillar", "r", "first", "item",
    "relation", "elements",
)

#: 别名 → 真实响应路径前缀。渲染函数的参数与循环变量都是别名：它们指向
#: 响应里的某个位置，但名字本身不出现在响应里。翻译回去，提取出的路径
#: 才能与契约对账。
ALIASES: dict[str, str] = {
    "data": "",       # post() 的解析结果：任一响应的根
    "payload": "",    # 响应根
    "chart": "",      # 命盘对象本体（/api/chart 的根；multi 的 chart 子键同形）
    "elements": "elements",  # chart.elements 的局部别名（Phase 5.3 五行普查）
    "evidence": "results[].analysis.analysis.evidence",
    "critique": "results[].analysis.critique",
    "citation": "results[].analysis.analysis.evidence.chain[].citation",
    "condition": "results[].analysis.analysis.evidence.chain[].conditions[]",
    "link": "results[].analysis.analysis.evidence.chain[]",
    "pillar": "pillars[]",
    "relation": "relations[]",
    "window": "windows[]",
    "signal": "windows[].signals[]",
    "r": "results[]",
    "first": "results[]",
    "item": "fields[]",
}

#: 永远不是 API 字段的属性名（JS 内建属性），捕获到即丢弃。
NON_FIELD_PROPERTIES = frozenset({"length"})

#: 前端**请求体**里允许出现的字段（BirthRequest 的出生信息子集）。
#: true_solar_time/longitude/latitude 是条件字段：只在勾选真太阳时出现。
REQUEST_FIELDS = frozenset({
    "year", "month", "day", "hour", "minute",
    "gender", "true_solar_time", "longitude", "latitude",
})


def _js_source() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    assert match, "index.html 里找不到 <script> 块"
    return match.group(1)


def _code_without_comments(js: str) -> str:
    """剥掉块注释与行注释。

    注释里提到的字段名不是读取 —— 「缺五行」死代码的教训就以注释形式
    留在 UI 里，不剥掉它会被误登记成一次读取。行注释的 ``//`` 用负向
    先行避开 ``://``（URL 协议头），尽管本文件的 JS 里没有硬编码 URL。
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", js)


def _flatten(value: object, prefix: str = "") -> set[str]:
    """把响应体摊平成点分路径集合，列表元素用 ``[]`` 记号。"""
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.add(path)
            paths |= _flatten(child, path)
    elif isinstance(value, list):
        for element in value:
            paths |= _flatten(element, f"{prefix}[]")
    return paths


def _sample_paths() -> set[str]:
    """真实响应的路径并集。契约里的每条路径都要能在这里找到。"""
    paths: set[str] = set()
    for endpoint, body in SAMPLES:
        response = client.post(endpoint, json=body)
        paths |= _flatten(response.json())
    return paths


def _extract_response_reads(js: str) -> set[str]:
    """静态提取 JS 里对 API 响应属性的读取路径（经别名归一化）。

    每个属性段都带两道断言：``(?![a-zA-Z_])`` 保证捕获的是完整标识符
    （防止 ``filter`` 被回溯成 ``filte``），``(?!\\s*\\()`` 保证它不是
    方法调用（``.some(``、``.map(``、``.toFixed(``）。JS 内建属性
    （``length``）显式丢弃。根变量经 ``ALIASES`` 翻译成真实响应路径前缀。
    """
    js = _code_without_comments(js)
    roots = "|".join(DATA_ROOTS)
    segment = r"([a-zA-Z_]+)(?![a-zA-Z_])(?!\s*\()"
    pattern = re.compile(
        rf"\b({roots})\.{segment}"
        rf"(?:\.{segment})?(?:\.{segment})?(?:\.{segment})?(?:\.{segment})?"
    )
    reads: set[str] = set()
    for match in pattern.finditer(js):
        parts = [match.group(1)] + [g for g in match.groups()[1:] if g]
        parts = [p for p in parts if p not in NON_FIELD_PROPERTIES or parts.index(p) == 0]
        if len(parts) == 1:
            continue  # 光秃秃一个根变量名不是读取
        prefix = ALIASES.get(parts[0], "")
        tail = ".".join(parts[1:])
        reads.add(f"{prefix}.{tail}" if prefix else tail)
    return reads


def _extract_request_fields(js: str) -> set[str]:
    """提取 birth() 构建的请求体字段：对象字面量键 + body.X 赋值。"""
    body_match = re.search(r"function birth\(\)\s*\{(.*?)\n\}", js, re.S)
    assert body_match, "找不到 birth() 函数体"
    body_source = body_match.group(1)
    fields = set(re.findall(r"^\s{4}([a-z_]+):", body_source, re.M))
    fields |= set(re.findall(r"\bbody\.([a-z_]+)\s*=", body_source))
    return fields


def _extract_endpoints(js: str) -> set[str]:
    return set(re.findall(r'post\(\s*"([^"]+)"', js))


# ── 后端方向：声明的每条路径都真实存在 ────────────────────────────────


def test_declared_response_paths_resolve_in_real_responses():
    sample_paths = _sample_paths()
    missing = sorted(RESPONSE_CONTRACT - sample_paths)
    assert not missing, (
        "响应契约里的路径在真实响应中不存在（后端漂移或样本选型失效）：\n"
        + "\n".join(f"  - {path}" for path in missing)
    )


def test_contract_is_not_vacuous():
    """契约本身不能是空转的：条目量要够，且样本响应不能是空的。"""
    assert len(RESPONSE_CONTRACT) > 50, "契约条目过少，检查是否被误删"
    for endpoint, body in SAMPLES:
        response = client.post(endpoint, json=body)
        # 唯一允许的非 200 样本是 422 那条（month=13，验 fields 结构）。
        expected = 422 if body.get("month") == 13 else 200
        assert response.status_code == expected, (
            f"样本 {endpoint} 返回了意外状态码 {response.status_code}"
        )


# ── 前端方向：JS 实际读取的路径都被契约声明 ───────────────────────────


def test_frontend_reads_only_declared_response_paths():
    reads = _extract_response_reads(_js_source())
    undeclared = sorted(reads - RESPONSE_CONTRACT)
    assert not undeclared, (
        "前端读取了契约未声明的响应路径（前端漂移？"
        "若是合理的新读法，先加进 RESPONSE_CONTRACT 再改 JS）：\n"
        + "\n".join(f"  - {path}" for path in undeclared)
    )


def test_frontend_reads_a_real_subset_of_the_contract():
    """反向：声明集合不能远超前端实际读取 —— 否则契约会腐烂成愿望清单。"""
    reads = _extract_response_reads(_js_source())
    unread = RESPONSE_CONTRACT - reads
    assert len(unread) <= len(RESPONSE_CONTRACT) // 2, (
        f"契约有 {len(unread)}/{len(RESPONSE_CONTRACT)} 条未被前端读取，"
        "契约正在腐烂成愿望清单"
    )


# ── 请求方向：前端发的字段与端点都合法 ────────────────────────────────


def test_frontend_sends_only_declared_request_fields():
    fields = _extract_request_fields(_js_source())
    assert fields, "birth() 里提取不到请求字段，检查正则是否失效"
    undeclared = sorted(fields - REQUEST_FIELDS)
    assert not undeclared, f"前端发送了未声明的请求字段：{undeclared}"


def test_frontend_covers_the_required_birth_fields():
    """必填字段一个都不能少 —— 少一个就是整个请求 422。"""
    schema = client.get("/openapi.json").json()
    birth = schema["components"]["schemas"]["BirthRequest"]
    required = set(birth.get("required", []))
    fields = _extract_request_fields(_js_source())
    missing = sorted(required - fields)
    assert not missing, f"前端请求体缺少必填字段：{missing}"


def test_frontend_posts_only_registered_endpoints():
    endpoints = _extract_endpoints(_js_source())
    assert endpoints, "提取不到 post() 目标，检查正则是否失效"
    schema = client.get("/openapi.json").json()
    registered = {
        path for path, methods in schema["paths"].items() if "post" in methods
    }
    unknown = sorted(endpoints - registered)
    assert not unknown, f"前端 POST 了未注册的端点：{unknown}"


# ── DOM 方向：JS 引用的每个 id 都存在于 HTML ──────────────────────────


def test_every_js_referenced_id_exists_in_html():
    html = INDEX_HTML.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    referenced = set(re.findall(r'\$\("([^"]+)"\)', _js_source()))
    missing = sorted(referenced - ids)
    assert not missing, f"JS 引用了 HTML 里不存在的 id：{missing}"


def test_dom_variables_never_shadow_data_roots():
    """DOM 变量不得与数据根变量同名。

    静态提取按变量名锚定属性路径。若 DOM 元素与 API 数据共用一个名字
    （曾经的教训：出处锚元素叫 link，与证据链循环变量 link 撞名），
    anchor.href 会被误登记成响应字段 —— 契约要么漏真要么收假。
    DOM 元素由 ``el()`` 创建，所以只查这条创建路径。
    """
    js = _code_without_comments(_js_source())
    dom_names = set(re.findall(r"\b(?:const|let|var)\s+([a-z_]+)\s*=\s*el\(", js))
    shadowing = sorted(dom_names & set(DATA_ROOTS))
    assert not shadowing, f"DOM 变量与数据根同名：{shadowing}"


def test_index_page_uses_textcontent_not_innerhtml():
    """注入面纪律：数据渲染不走 innerHTML。

    这条与契约测试同级重要 —— 契约保证「读得对」，这条保证「读到的
    坏数据不会变成 HTML」。两个断言在同一份 JS 上互为补充。
    """
    js = _code_without_comments(_js_source())
    assert not re.search(r"\.innerHTML\s*=", js), "index.html 的 JS 不得写入 innerHTML"
