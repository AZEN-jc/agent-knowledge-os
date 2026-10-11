"""LLM provider 协议与测试用假实现。

Phase 4 的第一步不是「接上大模型」，而是先把**边界**钉死：模型能看到什么输入、
必须给出什么形状的输出、越界时会发生什么。这一层不依赖任何外部服务，
也不读环境变量 —— 真 provider 的接线是后续工作。

provider 的接口刻意做窄：只有 ``complete(request) -> str``。没有工具调用、
没有多轮记忆、没有流式回调。接口越窄，能绕过证据链的地方就越少。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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
