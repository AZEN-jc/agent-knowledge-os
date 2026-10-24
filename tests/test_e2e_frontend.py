"""前端 E2E：真实浏览器跑通主链路（Phase 5.2）。

契约测试（``test_frontend_contract.py``）盯着**字段路径**，这个文件盯着
**行为**：点击、填写、等待渲染、断言 DOM。两类测试互为补充 —— 前者在
没有浏览器的环境里也能跑（CI 的常备门禁），后者需要 Chromium。

**没有浏览器时整套 skip，不是 fail。** 开发机上
``pip install playwright && playwright install chromium`` 之后自然跑起来；
CI 里由 ``.github/workflows/ci.yml`` 的专门步骤装好再跑。缺浏览器是
环境事实，不是产品缺陷 —— 把它变成红测试只会训练人忽略红测试。

链路选择（与 5.1 信息架构的用户流程一一对应）：

1. 主流程：填生辰 → 多主题分析 → 命盘区 + 证据链区出现；
2. 真太阳时：勾选展开经纬度 → 提交 → 命盘头行带 ``+tst`` 版本号；
3. 字段级错误：月份填 13 → 错误贴在月份输入框下面，不是只在顶部；
4. 时间轴：起止年 → 流年块渲染。
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="未安装 playwright")

from playwright.sync_api import sync_playwright

#: 本地开发可用系统 Chrome 跑 E2E，不必下载 170MB 的捆绑浏览器：
#: ``MINGLI_E2E_CHANNEL=chrome python -m pytest tests/test_e2e_frontend.py -q``
#: CI 不设这个变量 —— 那边用 ``playwright install chromium`` 的捆绑浏览器，
#: 不依赖镜像里预装什么。channel 的其他合法值见 Playwright 文档
#: （msedge 等），本仓库只承诺 chrome 这一种本地路径。
CHANNEL = os.environ.get("MINGLI_E2E_CHANNEL") or None


def _browser_available() -> bool:
    """浏览器是否可用。

    两种跳过理由要分开：包装了但没跑 ``playwright install chromium``
    （bundled 二进制缺失）时 launch() 抛的是 "Executable doesn't exist"，
    不是 skip —— 没有这道检查，CI 主步骤（只装包不装浏览器）会被动
    变红，E2E 从门禁退化成噪声。设了 CHANNEL 时走系统浏览器，由
    launch() 自己报错，这里不再替它判断。
    """
    if CHANNEL:
        return True
    try:
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _browser_available(),
    reason="未安装 Chromium 浏览器（playwright install chromium，或设 MINGLI_E2E_CHANNEL=chrome）",
)

import uvicorn  # noqa: E402

from api.server import app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def base_url():
    """在本线程起一个真实 uvicorn，跑完即关。

    为什么不用 TestClient：E2E 要验的是**浏览器与服务器之间**那一层 ——
    fetch、CORS 无关但 JSON 往返、静态文件服务、以及页面 JS 在真实
    HTTP 响应上的行为。TestClient 跳过网络，正好跳过要验的东西。
    """
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn 15 秒内没起来")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=CHANNEL)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser, base_url):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(base_url, wait_until="domcontentloaded")
    yield page
    context.close()


def _fill_birth(page, *, month: int = 6, day: int = 15, hour: int = 12) -> None:
    page.fill("#year", "1990")
    page.fill("#month", str(month))
    page.fill("#day", str(day))
    page.fill("#hour", str(hour))
    page.fill("#minute", "30")


# ── 1. 主流程 ─────────────────────────────────────────────────────────


def test_main_flow_shows_chart_and_evidence(page):
    _fill_birth(page)
    page.click("#run")

    chart = page.locator("#out-chart")
    chart.wait_for(state="visible", timeout=15000)
    # 柱名本地化：命盘表第一列是中文柱名，不是 year/month/day/hour。
    assert "年柱" in chart.inner_text()
    assert "时柱" in chart.inner_text()
    # 算法版本行：provider 与版本号必须出现在界面上。
    assert "sxtwl-2.0.7" in chart.inner_text()
    # 五行普查（Phase 5.3）：计数行随命盘渲染。这一行曾读一个 provider
    # 从来没产出过的键，从上线起就是死的 —— 现在先有测试再有产出。
    assert "五行计数" in chart.inner_text()
    # 四列传统排布：表头是四个柱名各占一列。
    headers = chart.locator("table th")
    assert headers.count() == 5  # 行首空单元格 + 四柱
    assert headers.nth(1).inner_text() == "年柱"
    assert headers.nth(4).inner_text() == "时柱"

    analysis = page.locator("#out-analysis")
    analysis.wait_for(state="visible", timeout=15000)
    text = analysis.inner_text()
    assert "证据强度" in text  # 强度算式随证据链披露
    assert "审查" in text     # Critic 结论


# ── 2. 真太阳时 ───────────────────────────────────────────────────────


def test_true_solar_time_toggle_reveals_geo_and_marks_the_version(page):
    geo = page.locator("#geo-row")
    assert not geo.is_visible(), "经纬度行默认应隐藏"

    page.check("#tst")
    assert geo.is_visible(), "勾选真太阳时后经纬度行应展开"
    page.fill("#longitude", "87.6")
    page.fill("#latitude", "43.8")

    _fill_birth(page, month=2, day=1, hour=23)
    page.fill("#minute", "50")
    page.click("#run")

    chart = page.locator("#out-chart")
    chart.wait_for(state="visible", timeout=15000)
    # 口径必须看得见：版本号带 +tst，两张不同口径的命盘不共用一个版本。
    assert "+tst" in chart.inner_text()


def test_true_solar_time_without_longitude_reports_on_the_field(page):
    page.check("#tst")
    _fill_birth(page)
    page.click("#run")

    # 客户端守卫：不等服务端往返，错误直接贴在经度输入框下。
    error = page.locator("#longitude").locator("xpath=ancestor::div[contains(@class,'field')]//div[contains(@class,'field-error')]")
    error.wait_for(state="visible", timeout=5000)
    assert "经度" in error.inner_text()
    # 命盘区不应出现 —— 请求根本没发出去。
    assert not page.locator("#out-chart").is_visible()


# ── 3. 字段级错误 ─────────────────────────────────────────────────────


def test_field_level_error_appears_under_the_input(page):
    """服务端 422 的 fields 数组要贴到对应输入框下面。

    为什么用 year 而不是 month：HTML 给 month/hour/day/minute 写了
    min/max，浏览器**原生约束验证**在 submit 事件之前就把越界值拦了
    （弹原生气泡）—— 那条路根本到不了服务端，也就验不到 fields 渲染。
    year 没写 min/max（策略边界 2–9997 在服务端），越界值会真的打到
    422 with fields。两层验证是互补的：原生管即时反馈，服务端管原生
    管不了的（策略边界、不存在的日期、口径冲突）。
    """
    page.fill("#year", "0")
    page.click("#run")

    error = page.locator("#year").locator("xpath=ancestor::div[contains(@class,'field')]//div[contains(@class,'field-error')]")
    error.wait_for(state="visible", timeout=10000)
    assert "2" in error.inner_text()  # 「公历年不能小于2」
    # 顶部错误框也保留（detail 字符串），两个表示同时在。
    assert page.locator("#error .error").count() >= 1


def test_native_validation_guards_the_range_constrained_inputs(page):
    """month 越界时浏览器原生验证先行：请求不发，我们的错误区不出现。

    这条钉住两层验证的边界。谁给 form 加 ``novalidate``、或删掉输入框的
    min/max，这条红 —— 那是验证策略的变更，不是顺手清理。反向的代价：
    没有原生层时，month=13 也要等一个服务端往返才报错。
    """
    _fill_birth(page, month=13)
    page.click("#run")
    page.wait_for_timeout(1000)  # 负向断言需要沉降窗口
    assert page.locator("#error .error").count() == 0
    assert not page.locator("#out-chart").is_visible()


# ── 4. 时间轴 ─────────────────────────────────────────────────────────


def test_timeline_renders_year_windows(page):
    _fill_birth(page)
    page.fill("#from", "2024")
    page.fill("#to", "2026")
    page.click("#timeline")

    timeline = page.locator("#out-timeline")
    timeline.wait_for(state="visible", timeout=15000)
    text = timeline.inner_text()
    assert "2024" in text
    assert "信号是结构描述" in text  # note 里的立场声明必须出现在界面上


# ── 5. 典籍库（Phase 5.4）─────────────────────────────────────────────


def test_library_browser_shows_books_with_verifiable_citations(page):
    """典籍库：按底本聚合的规则卡，每条带 URN、逐字原文与可打开链接。"""
    page.click("#library-btn")

    library = page.locator("#out-library")
    library.wait_for(state="visible", timeout=15000)
    text = library.inner_text()
    assert "三命通會" in text                    # 已录入的底本
    assert "urn:divination:" in text            # 规范引用标识
    assert "原文：" in text                       # 逐字原文
    # 出处必须真的可点开，且带 noopener。
    link = library.locator("a", has_text="打开出处").first
    href = link.get_attribute("href")
    assert href and href.startswith("http")
    assert link.get_attribute("rel") == "noopener noreferrer"


def test_library_browser_discloses_the_backlog(page):
    """待录入典籍也要看得见 —— 只展示已录入的会让人以为库已覆盖这些书。"""
    page.click("#library-btn")

    library = page.locator("#out-library")
    library.wait_for(state="visible", timeout=15000)
    assert "待录入典籍" in library.inner_text()
