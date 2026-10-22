"""HttpLLMProvider 的测试：走真实 socket，但不联网。

## 为什么用本地回环服务器

契约的**逻辑**已经由 ``test_llm_contract.py`` 用假 provider 覆盖。这里要覆盖的是
契约在**真实传输**下的行为：超时、非 200、响应体不是 JSON、连接被拒、空响应体。
这些失败只会在真实 socket 上出现，mock 掉 ``complete`` 就全看不见了 ——
而它们恰恰是生产里最常见的失败。

所以测试起一个 ``http.server`` 回环服务器，让 provider 真的去连它。
**不访问外网**，因此 CI 与离线环境都能跑。

## 代理这个坑

``urllib`` 默认读 ``http_proxy`` 环境变量。本机这些变量指向本地代理，
回环地址走代理会被拦成连接失败，于是「连本地服务器」这件不该失败的事会失败，
且报错指向网络。provider 里已显式装空 ``ProxyHandler``；
这里有一条测试专门验它：在设了代理环境变量的子进程里跑，仍然要连得上。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from agents.llm import HttpLLMProvider, LLMRequest, ProviderError

REPO = Path(__file__).resolve().parent.parent

REQUEST = LLMRequest(system="系统提示", user='{"证据": "链"}')


class _Handler(BaseHTTPRequestHandler):
    """按 ``responses`` 队列作答；每次请求弹出下一条。

    ``last_body`` / ``last_headers`` 记录最近一次请求，供测试断言
    「到底发出去了什么」—— provider 的请求内容是契约的一部分。
    """

    responses: ClassVar[list[tuple[int, dict[str, str], bytes]]] = []
    last_body: ClassVar[str] = ""
    last_headers: ClassVar[dict[str, str]] = {}

    def do_POST(self) -> None:  # http.server 的命名约定
        length = int(self.headers.get("Content-Length", 0))
        type(self).last_body = self.rfile.read(length).decode("utf-8")
        type(self).last_headers = dict(self.headers)
        status, headers, payload = self.responses.pop(0)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # 静音，别把测试输出刷满
        pass


@pytest.fixture()
def server():
    """起一个回环服务器；``respond`` 用来排定下一个响应。"""
    _Handler.responses = []
    _Handler.last_body = ""
    _Handler.last_headers = {}
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield _ServerHandle(httpd)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class _ServerHandle:
    def __init__(self, httpd: HTTPServer) -> None:
        self.httpd = httpd
        self.host, self.port = httpd.server_address

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/v1/complete"

    def respond(self, payload: bytes, *, status: int = 200) -> None:
        _Handler.responses.append(
            (status, {"Content-Type": "application/json"}, payload)
        )


def provider(endpoint: str, **kwargs) -> HttpLLMProvider:
    kwargs.setdefault("model", "test-model")
    return HttpLLMProvider(endpoint=endpoint, **kwargs)


# ── 正常路径 ──────────────────────────────────────────────────────────


def test_it_posts_and_returns_the_text(server):
    server.respond(json.dumps({"text": "这是一段结论"}).encode("utf-8"))

    result = provider(server.endpoint).complete(REQUEST)

    assert result == "这是一段结论"


def test_it_sends_the_whole_request_and_declares_the_model(server):
    """请求体必须带 model / system / user 三段，一段不能少。"""
    server.respond(json.dumps({"text": "ok"}).encode("utf-8"))

    provider(server.endpoint, model="mingli-1").complete(REQUEST)

    sent = json.loads(_Handler.last_body)
    assert sent["model"] == "mingli-1"
    assert sent["system"] == "系统提示"
    assert sent["user"] == '{"证据": "链"}'


def test_it_sends_the_api_key_as_a_bearer_token(server):
    server.respond(json.dumps({"text": "ok"}).encode("utf-8"))

    provider(server.endpoint, api_key="secret-token").complete(REQUEST)

    assert _Handler.last_headers.get("Authorization") == "Bearer secret-token"
    assert _Handler.last_headers.get("Content-Type") == "application/json"


def test_a_bare_json_string_is_accepted(server):
    """端点也可以只回一串 JSON 字符串 —— 那也是合法的模型输出。"""
    server.respond(json.dumps("直接给文本").encode("utf-8"))

    assert provider(server.endpoint).complete(REQUEST) == "直接给文本"


# ── 失败路径：每一种都必须是 ProviderError，不能伪装成成功 ─────────────


def test_a_non_200_status_is_a_provider_error(server):
    server.respond(b'{"error": "quota exceeded"}', status=429)

    with pytest.raises(ProviderError, match="429"):
        provider(server.endpoint).complete(REQUEST)


def test_a_non_json_body_is_a_provider_error(server):
    server.respond(b"<html>gateway error</html>")

    with pytest.raises(ProviderError, match="不是 JSON"):
        provider(server.endpoint).complete(REQUEST)


def test_an_empty_body_is_a_provider_error(server):
    server.respond(b"")

    with pytest.raises(ProviderError, match="空响应体"):
        provider(server.endpoint).complete(REQUEST)


def test_a_response_without_text_is_a_provider_error(server):
    """响应形状不对时报错，**不猜字段名**。

    猜一个字段名会把服务端的错误响应当成模型输出，而「模型说了句怪话」与
    「服务端返回了错误页」在后续处理里完全不是一回事。
    """
    server.respond(json.dumps({"choices": [{"message": "..."}]}).encode("utf-8"))

    with pytest.raises(ProviderError, match="缺少 text 字段"):
        provider(server.endpoint).complete(REQUEST)


def test_an_unreachable_endpoint_is_a_provider_error():
    """连不上时给出可读原因，而不是把 OSError 原样抛出去。"""
    closed = HTTPServer(("127.0.0.1", 0), _Handler)
    host, port = closed.server_address
    closed.server_close()  # 占位后立刻关，保证没人监听这个端口

    with pytest.raises(ProviderError, match="无法连接"):
        provider(f"http://{host}:{port}/v1").complete(REQUEST)


def test_a_refused_connection_is_a_provider_error_not_a_bare_oserror():
    """连接被拒必须是 ProviderError，而不是裸 ``OSError``。

    ``127.0.0.1:1`` 没人监听，连接会被立刻拒绝。真正要验的是异常类型被收成
    ProviderError —— 调用方据此区分「该降级」与「代码 bug」。
    """
    with pytest.raises(ProviderError):
        provider("http://127.0.0.1:1/v1", timeout=2.0).complete(REQUEST)


# ── 构造期校验 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("endpoint", ["", "   ", "ftp://x", "not-a-url"])
def test_a_bad_endpoint_is_rejected_at_construction(endpoint):
    with pytest.raises(ProviderError, match="endpoint"):
        HttpLLMProvider(endpoint=endpoint, model="m")


def test_a_non_positive_timeout_is_rejected_at_construction():
    with pytest.raises(ProviderError, match="timeout"):
        HttpLLMProvider(endpoint="http://x/v1", model="m", timeout=0)


# ── 代理：环境变量不该改写目标端点 ────────────────────────────────────


def test_it_connects_even_when_proxy_environment_variables_are_set(server):
    """设了 ``http_proxy`` 也必须连得上回环服务器。

    这条是**本机真实踩过的坑**：``urllib`` 默认读代理环境变量，回环地址走
    代理会被拦成连接失败，于是「连本地服务器」这件不该失败的事失败了，
    且报错信息指向网络，极难定位。provider 里显式装空 ``ProxyHandler``，
    这条测试钉住那个决定。
    """
    server.respond(json.dumps({"text": "绕过代理"}).encode("utf-8"))

    completed = subprocess.run(
        [
            sys.executable, "-c",
            "import sys\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "from agents.llm import HttpLLMProvider, LLMRequest\n"
            "p = HttpLLMProvider(endpoint=%r, model='m')\n"
            "print(p.complete(LLMRequest(system='s', user='u')))\n" % server.endpoint,
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ,
             "http_proxy": "http://127.0.0.1:9",
             "https_proxy": "http://127.0.0.1:9",
             "HTTP_PROXY": "http://127.0.0.1:9"},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "绕过代理" in completed.stdout
