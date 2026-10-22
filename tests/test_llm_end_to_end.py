"""端到端：真实 HTTP provider 驱动完整分析，契约仍然成立。

## 为什么要有这一层

``test_llm_provider_http.py`` 验的是 provider **自己**的行为；
``test_llm_contract.py`` 验的是契约的**逻辑**（用假 provider）。
两者都不回答这个问题：**一个真的会走网络的 provider，接进服务层之后，
整套约束还守得住吗？**

这里用回环服务器当一个「真」模型端点，让 ``MingLiService`` 真的通过 HTTP
出稿，然后断言三件事：

1. **走的是 LLM 路径**（``draft.source == "llm"``），且 provider / model 有记录；
2. **喂给网络的只有证据链** —— 请求体里不能出现出生日期、经度、原始命盘；
3. **越界引用仍然被拦** —— 端点故意返回一个证据链之外的规则 ID，
   它必须被剔除并记进 ``contract_violations``，而不是静默消失。

第 2 条是 Phase 4 的核心承诺在传输层的落点：模型不该拿到生辰。
``build_prompt`` 的签名里没有 ``Chart``，但签名防不住「有人往 user 里多塞
东西」，所以这里直接看**字节**。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from agents.llm import HttpLLMProvider
from runtime.mingli_service import MingLiService

BIRTH = {"year": 1990, "month": 2, "day": 1, "hour": 12, "gender": "男"}


class _Handler(BaseHTTPRequestHandler):
    """把收到的请求存下来，并回一段可配置的模型输出。"""

    seen: ClassVar[list[dict]] = []
    reply: ClassVar[dict | None] = None

    def do_POST(self) -> None:  # http.server 的命名约定
        length = int(self.headers.get("Content-Length", 0))
        type(self).seen.append(json.loads(self.rfile.read(length).decode("utf-8")))
        # **两层 JSON，别搞混。** 传输层是 {"text": "..."}，text 的值是模型的
        # 原始输出；而契约要求模型输出本身又是 {"rule_ids":..., "text":...}。
        # 键名都叫 text，直接 json.dumps(reply) 会让 parse_draft 收到一句
        # 中文而不是 JSON —— 第一版就栽在这里，报「草稿不是合法 JSON」。
        payload = json.dumps(
            {"text": json.dumps(self.reply, ensure_ascii=False)}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def endpoint():
    _Handler.seen = []
    _Handler.reply = None
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://{httpd.server_address[0]}:{httpd.server_address[1]}/v1"
    finally:
        httpd.shutdown()
        httpd.server_close()


def service(endpoint: str) -> MingLiService:
    return MingLiService(provider=HttpLLMProvider(endpoint=endpoint, model="e2e-model"))


def conforming_reply(evidence: dict) -> dict:
    """按证据链构造一段**真的能过 Critic** 的输出。

    三件事都要做对，少一件 Critic 就拦：

    1. 只引证据链里的规则 ID；
    2. 写明「证据强度」及数值（低强度时必须披露）；
    3. **主题覆盖不足时原样带上 coverage_note** —— 「事业」当前没有专属规则，
       状态是 base_only，Critic 要求把它如实告诉读者。

    第 3 条是第一版测试漏掉的：它让一个合规回复被 Critic 判为「未披露覆盖
    不足」。那不是 bug，是契约在真实 provider 路径下真的在管事。
    """
    text = f"证据强度 {evidence['strength']:.2f}，以上为命盘结构证据的复述。"
    if evidence["status"] != "covered":
        text += evidence["coverage_note"]
    return {
        "rule_ids": [rule["rule_id"] for rule in evidence["chain"]][:2],
        "text": text,
    }


def test_a_real_http_provider_drives_the_llm_draft_path(endpoint):
    _Handler.reply = None  # 先占位，拿到证据后再填
    svc = service(endpoint)

    # 第一轮：先用模板跑一次拿到证据链，据此构造合规回复。
    template = MingLiService().analyze(BIRTH, "事业")
    _Handler.reply = conforming_reply(template.analysis["evidence"])

    result = svc.analyze(BIRTH, "事业")

    draft = result.analysis["draft"]
    assert draft["source"] == "llm"
    assert draft["provider"] == "http"
    assert draft["model"] == "e2e-model"
    assert draft["contract_violations"] == []
    # Critic 是确定性审查，provider 路径下也要过。
    assert result.critique["passed"] is True


def test_the_network_only_ever_sees_the_evidence_chain(endpoint):
    """**本条是 Phase 4 的核心承诺**：字节层面确认模型拿不到生辰。"""
    _Handler.reply = {"rule_ids": [], "text": "证据不足"}
    svc = service(endpoint)

    svc.analyze(BIRTH, "事业")

    assert _Handler.seen, "一次请求都没发出去"
    sent = _Handler.seen[0]
    blob = json.dumps(sent, ensure_ascii=False)

    # 出生信息一个字都不能出现。
    for forbidden in ("1990", "longitude", "latitude", "timezone", "gender"):
        assert forbidden not in blob, f"请求体里出现了 {forbidden}"
    # user 段必须且只能是证据链 JSON。
    evidence = json.loads(sent["user"])
    assert "chain" in evidence and "facts" in evidence
    # 系统提示词必须原样带到。
    assert sent["system"].startswith("你是命理证据的复述者")


def test_an_out_of_chain_rule_id_is_stripped_and_recorded(endpoint):
    """端点故意返回证据链之外的规则 ID：剔除 + 记违约，两件事都要发生。"""
    _Handler.reply = {"rule_ids": ["STRUCT_PATTERN_999"], "text": "证据强度 0.50"}
    svc = service(endpoint)

    result = svc.analyze(BIRTH, "事业")

    draft = result.analysis["draft"]
    assert "STRUCT_PATTERN_999" not in draft["cited_rules"]
    assert any("STRUCT_PATTERN_999" in v for v in draft["contract_violations"])
    # Critic 也要把它报出来 —— 用户看得见，不是只留在日志里。
    assert result.critique["passed"] is False


def test_a_fabricated_urn_in_the_text_is_caught_by_the_critic(endpoint):
    """模型在正文里编一个出处角标，Critic 必须判「疑似编造」。"""
    _Handler.reply = {
        "rule_ids": [],
        "text": "古法记为吉格〔urn:divination:bazi:fake:ws0000000:j1.x.y〕，证据强度 0.50",
    }
    svc = service(endpoint)

    result = svc.analyze(BIRTH, "事业")

    assert result.critique["passed"] is False
    assert any("编造" in issue for issue in result.critique["issues"])


def test_without_a_provider_the_template_path_is_untouched(endpoint):
    """不注入 provider 时，行为必须与 Phase 3 逐字一致。

    Phase 4 加了 LLM 路径，但默认路径不许被顺手改掉 —— 那是 1204 条测试
    正在守的东西，这里再确认一次接线没有副作用。
    """
    _Handler.reply = {"rule_ids": [], "text": "不应被调用"}
    svc = MingLiService()

    result = svc.analyze(BIRTH, "事业")

    assert result.analysis["draft"]["source"] == "template"
    assert _Handler.seen == [], "没有 provider 却发出了请求"
