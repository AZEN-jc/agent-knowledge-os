"""E2E 共享脚手架：真实 uvicorn + 真实 Chromium（Phase 5.2 / 5.9）。

放在 conftest 而不是某个测试文件里：跨模块 import fixture 会让 pytest
按不同模块路径各注册一份 session 作用域实例，第二份在已有事件循环的
上下文里启动 Playwright 会直接报「Sync API inside the asyncio loop」。
conftest 里的 fixture 全局唯一，没有这个问题。

两条跳过路径分开处理：

- **包没装**：测试模块顶部的 ``pytest.importorskip`` 负责（import 阶段
  就停）；
- **浏览器没下载**：这里的 ``browser`` fixture 负责 ``pytest.skip`` ——
  launch() 抛的是「Executable doesn't exist」，那不是产品缺陷，是环境
  事实。缺浏览器变红测试只会训练人忽略红测试。
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from api.server import app

#: 本地开发可用系统 Chrome 跑 E2E，不必下载 170MB 的捆绑浏览器：
#: ``MINGLI_E2E_CHANNEL=chrome python -m pytest tests/test_e2e_frontend.py -q``
#: CI 不设这个变量 —— 那边用 ``playwright install chromium`` 的捆绑浏览器。
CHANNEL = os.environ.get("MINGLI_E2E_CHANNEL") or None


def chromium_available() -> bool:
    """浏览器是否可用（包已 import 的前提下调用）。

    设了 CHANNEL 时走系统浏览器，由 launch() 自己报错，这里不再替它判断。
    """
    if CHANNEL:
        return True
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).exists()
    except Exception:
        return False


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def base_url():
    """在本线程起一个真实 uvicorn，跑完即关。

    为什么不用 TestClient：E2E 要验的是**浏览器与服务器之间**那一层 ——
    fetch、JSON 往返、静态文件服务、以及页面 JS 在真实 HTTP 响应上的
    行为。TestClient 跳过网络，正好跳过要验的东西。
    """
    import uvicorn

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
    from playwright.sync_api import sync_playwright

    if not chromium_available():
        pytest.skip(
            "未安装 Chromium 浏览器（playwright install chromium，"
            "或设 MINGLI_E2E_CHANNEL=chrome）"
        )
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True, channel=CHANNEL)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser, base_url):
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,  # Phase 5.7：报告导出走浏览器下载
    )
    page = context.new_page()
    page.goto(base_url, wait_until="domcontentloaded")
    yield page
    context.close()
