"""LLM provider 协议、测试用假实现，以及一个可注入的 HTTP provider。

Phase 4 的第一步不是「接上大模型」，而是先把**边界**钉死：模型能看到什么输入、
必须给出什么形状的输出、越界时会发生什么。这一层不依赖任何外部服务，
也不读环境变量 —— 服务层没有「读一个环境变量就启用 LLM」的开关。

**为什么要有 HttpLLMProvider。** 假 provider 只能验证契约的**逻辑**，验证不了
契约在真实传输下的行为：超时、非 200、响应体不是 JSON、网络中断。这些恰恰是
生产里最常见的失败，而它们的共同点是**不能伪装成分析成功**（任务书硬性要求）。
于是这里给一个走 HTTP 的实现，测试用本地回环服务器驱动它 —— 不联网，
但走的是真实的 socket 路径。

**为什么它不读环境变量。** 服务层要的是「没有开关，就没有『以为开了其实没开』
的空间」。要启用 LLM 就显式传一个 provider 实例进来，调用方自己决定 key 从哪来。
这个类同样不读环境变量：endpoint / key 都是构造参数。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """provider 层面的失败：网络、超时、认证、响应形状。

    与普通异常分开是为了让调用方能区分两件事：

    - **provider 故障** —— 该降级到确定性模板，并如实告诉用户「这次没走模型」。
      把它当成分析成功是任务书明令禁止的。
    - **代码 bug** —— 比如契约层传了个 None。那应该响亮地炸，不该被降级掩盖。

    只捕获 :class:`ProviderError` 就能做到这个区分，不用去匹配异常消息。
    """


@dataclass(frozen=True)
class LLMRequest:
    """一次请求。只有两段文本，没有别的通道。"""

    system: str
    user: str

    def to_dict(self) -> dict[str, str]:
        return {"system": self.system, "user": self.user}


@runtime_checkable
class LLMProvider(Protocol):
    """把请求变成一段文本。

    刻意不定义「返回结构化对象」的方法：结构化是**契约层**的职责
    （见 :mod:`agents.prompt`），不是 provider 的。provider 说得越花哨，
    越容易让人误以为「provider 已经保证合规了」。
    """

    name: str
    model: str

    def complete(self, request: LLMRequest) -> str:
        """返回模型的原始文本输出，不做任何清洗。"""
        ...


@dataclass
class FakeLLMProvider:
    """按脚本作答的假 provider。

    测试需要能**精确控制**模型说什么，包括故意说错，所以这里不是随机 mock，
    而是一个脚本队列：每次调用弹出下一条。

    脚本用尽时**抛错，而不是返回兜底文案**。返回兜底会让「少写了一条脚本」
    表现成「测试通过」—— 这是最坏的失败模式：测试看着很绿，实际什么都没验。

    ``requests`` 保留全部请求原文，供测试断言「喂给模型的到底是什么」。
    """

    responses: list[str]
    name: str = "fake"
    model: str = "scripted"
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError(
                f"假 provider 脚本已用尽：第 {len(self.requests)} 次调用没有对应响应。"
                "请补脚本，不要让测试靠兜底内容变绿。"
            )
        return self.responses.pop(0)


@dataclass(frozen=True)
class HttpLLMProvider:
    """走 HTTP 的 LLM provider；端点、模型名、密钥全部显式传入。

    **默认不启用。** 服务层不读环境变量，本类也不读：没有隐式开关，
    就没有「以为开了其实没开」的空间。要启用就在构造服务时显式注入。

    **为什么绕开系统代理。** ``urllib`` 默认读 ``http_proxy`` / ``https_proxy``
    环境变量。本机（以及多数桌面环境）这些变量指向一个本地代理，而回环地址
    走代理会被拦成连接失败 —— 于是「连本地测试服务器」这件不该失败的事会失败，
    且报错信息指向网络，极难定位。这里显式装一个空 ``ProxyHandler``：
    provider 要连的是它自己被告知的那个端点，不该被环境里的代理改写。

    **为什么用 urllib 而不是 requests。** 少一个依赖。MingLi 运行时只依赖
    sxtwl / fastapi / uvicorn / pydantic；为了一个 POST 引入 requests 不值得。
    """

    endpoint: str
    model: str
    api_key: str = ""
    timeout: float = 30.0
    name: str = "http"
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.endpoint.strip():
            raise ProviderError("HttpLLMProvider 需要 endpoint。")
        if not self.endpoint.startswith(("http://", "https://")):
            raise ProviderError(f"endpoint 必须是 http(s) 地址：{self.endpoint!r}")
        if self.timeout <= 0:
            raise ProviderError(f"timeout 必须为正数，实得 {self.timeout}")

    def complete(self, request: LLMRequest) -> str:
        body = json.dumps({
            "model": self.model,
            "system": request.system,
            "user": request.user,
        }).encode("utf-8")

        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # 空 ProxyHandler：显式不走任何代理，理由见类 docstring。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        try:
            with opener.open(
                urllib.request.Request(self.endpoint, data=body, headers=headers),
                timeout=self.timeout,
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", "replace")
            raise ProviderError(
                f"LLM 端点返回 {exc.code}：{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"无法连接 LLM 端点 {self.endpoint}：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderError(
                f"LLM 端点在 {self.timeout}s 内未响应"
            ) from exc
        except OSError as exc:
            # 连接重置、DNS 失败、TLS 错误都落在这里。
            raise ProviderError(f"连接 LLM 端点失败：{exc}") from exc

        return _extract_text(payload)


def _extract_text(payload: bytes) -> str:
    """从端点响应里取出模型文本。

    接受两种形状：``{"text": "..."}`` 或裸字符串。别的一律报 ProviderError ——
    响应对不上时最糟的做法是猜一个字段名，那会把服务端的错误响应当成模型输出，
    而「模型说了一句怪话」与「服务端返回了错误页」在后续处理里完全不是一回事。
    """
    if not payload:
        raise ProviderError("LLM 端点返回了空响应体")

    try:
        data: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"LLM 端点返回的不是 JSON：{exc}") from exc

    if isinstance(data, str):
        return data
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return data["text"]
    raise ProviderError(
        "LLM 端点响应缺少 text 字段（期望 {\"text\": \"...\"} 或裸 JSON 字符串），"
        f"实际键：{sorted(data) if isinstance(data, dict) else type(data).__name__}"
    )
