"""LLM 提示契约：模型只能看到证据链，只能引用证据链里出现过的规则。

Phase 4 的核心不是「接上大模型」，而是把「不许自由发挥」从一句文档里的口号
变成**三层可测的约束**：

1. **输入层** —— :func:`build_prompt` 的参数类型是
   :class:`~knowledge.evidence.Evidence`，**签名里没有 ``Chart``**。
   原始命盘、出生信息、全量规则库都不在模型能拿到的范围里，
   「编造命盘数据」于是不靠模型自觉，靠类型系统。
2. **输出层** —— 只接受 ``{"rule_ids": [...], "text": "..."}``。多一个字段、
   少一个字段、类型不对，都记违约。
3. **边界层** —— ``rule_ids`` 里任何一条不在证据链里的 ID 都会被**剔除**，
   并逐条记进 ``violations``。不是忽略，不是静默警告，是留痕。

契约本身也是数据：:func:`contract` 把系统提示词、输出 schema、边界规则和
禁用词表一起暴露出来，由 ``GET /api/llm/contract`` 返回，便于审计 ——
一份只写在源码注释里的契约，等于没有契约。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agents.llm import LLMRequest
from knowledge.evidence import Evidence

CONTRACT_VERSION = "2"

DRAFT_KEYS = ("rule_ids", "text")

FOOTNOTE_OPEN = "〔"
FOOTNOTE_CLOSE = "〕"
"""出处角标的分隔符。

全角方括号而不是 ``[...]``：半角方括号在中文正文里太常见（注释、补字），
把它当角标会误判。这里要的是一个**在正常行文里不会自然出现**的记号，
否则「挂没挂出处」这件事就没法用字符串判定，只能靠模型自觉。
"""

FOOTNOTE_PATTERN = re.compile(r"〔(urn:divination:[^〕\s]+)〕")
"""从结论正文里回收出处角标，用来反向查「有没有编造出处」。"""

LOW_STRENGTH_CEILING = 0.5
"""低于这个证据强度时，结论**必须**披露强度。

不是「强度低就不许说话」，而是「强度低时不许不说强度」。读者看到一句
没有强度标注的结论，会默认它很硬；而 0.3 和 0.8 的证据厚度完全不同。
"""

CERTAINTY_WORDS = (
    "一定",
    "必然",
    "注定",
    "肯定",
    "绝对",
    "毫无疑问",
    "铁定",
)
"""禁用词表。任意强度下都不许出现 —— 措辞的确定性不是强度能授权的。"""

STRENGTH_MARKER = "证据强度"
"""结论里必须出现这个字面量才算披露了强度。用固定短语而不是数值，
是因为数值的书写形式（0.4 / 0.40 / 四成）无法可靠匹配。"""

SYSTEM_PROMPT = """你是命理证据的复述者，不是推断者。

你会收到一份**证据链**（JSON）：命盘事实、命中的规则及其条件追踪、证据强度、
主题覆盖说明。你没有原始命盘，也不允许凭空补充任何命盘信息。

硬性要求：
1. 只能引用证据链里出现过的规则 ID。引用不存在的 ID 会被剔除并记为违约。
2. 不得新增命盘事实，不得编造规则，不得引入证据链之外的任何命理知识。
3. 不得给出吉凶、成败、时间、结果等预测判断；只复述证据说明了什么。
4. 禁止出现这些词：一定、必然、注定、肯定、绝对、毫无疑问、铁定。
5. 结论里必须写明「证据强度」并附上证据链里给出的数值。
6. 主题覆盖状态不是 covered 时，必须原样带上 coverage_note 的内容。
7. 证据链里 conflicts 非空时，必须写明存在规则分歧，并列呈现，不得替读者取舍。
8. 证据链为空时，只回一句「证据不足」，rule_ids 必须是空数组。
9. **凡引用 source_tier 为 classical 的规则，必须在该句断语后面挂上它的 urn，
   写作〔urn:divination:...〕，一字不改。** 出处就在该规则的 urn 字段里，
   照抄即可。不得改写、不得简写、不得凭记忆重建 —— 缺角标或角标对不上
   都会被判违约。结构层规则（source_tier 为 structural）不需要角标，
   它的条件追踪本身就是出处。

只输出下面这个 JSON，不要任何其他文字，不要 Markdown 代码块：

{"rule_ids": ["规则ID", "..."], "text": "结论正文"}
"""

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["rule_ids", "text"],
    "additionalProperties": False,
    "properties": {
        "rule_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "只能引用证据链里出现过的规则 ID；越界项会被剔除并记违约",
        },
        "text": {
            "type": "string",
            "description": (
                "结论正文，只复述证据，不做预测。"
                "引用了 classical 规则时，该句断语必须挂 〔urn:...〕 角标"
            ),
        },
    },
}

BOUNDARY_RULES: tuple[str, ...] = (
    "模型输入只有证据链（evidence.to_dict()），不含原始命盘、出生信息与全量规则库。",
    "输出必须是只含 rule_ids 与 text 两个键的 JSON 对象。",
    "rule_ids 里的每一项都必须出现在证据链中，否则被剔除并记为违约。",
    "禁用词表在任意证据强度下都生效。",
    "证据强度低于阈值时，结论必须披露强度，否则视为违约。",
    "主题覆盖不足与规则冲突都必须披露 —— Critic 查的是「说了没有」，不是「有没有」。",
    "典籍断语必须挂出处角标：引用了 classical 规则却没写它的 urn，视为违约。",
    "出处角标只能取自证据链：结论里出现证据链之外的 urn，视为编造出处。",
)

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```$", re.DOTALL)


@dataclass(frozen=True)
class Draft:
    """一份通过（或未通过）契约校验的草稿。"""

    text: str
    cited_rule_ids: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()

    @property
    def is_conforming(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "cited_rule_ids": list(self.cited_rule_ids),
            "violations": list(self.violations),
            "is_conforming": self.is_conforming,
        }


def evidence_payload(evidence: Evidence) -> str:
    """证据链的 JSON 正文。

    首次请求的 ``user`` 就是它本身，一个字节都不多 —— 测试直接断言
    ``json.loads(user) == evidence.to_dict()``，这样「输入里混进了别的东西」
    无法蒙混过关。
    """
    return json.dumps(
        _jsonable(evidence.to_dict()),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def build_prompt(evidence: Evidence) -> LLMRequest:
    """构造首次出稿的请求。"""
    return LLMRequest(system=SYSTEM_PROMPT, user=evidence_payload(evidence))


def build_revision_prompt(
    evidence: Evidence,
    draft: Draft,
    issues: tuple[str, ...] | list[str],
) -> LLMRequest:
    """把审查意见回灌，要求重写。

    重试同样**只给证据链**，不追加任何新信息 —— 否则「多轮修正」会变成
    「多轮加料」，越修离证据越远。
    """
    lines = [
        evidence_payload(evidence),
        "",
        "── 你上一次的输出 ──",
        render_draft(draft.cited_rule_ids, draft.text),
        "",
        "── 审查意见（必须逐条修正）──",
        *[f"- {issue}" for issue in issues],
        "",
        "重新输出 JSON。除修正上述问题外，内容不得与证据链冲突。",
    ]
    return LLMRequest(system=SYSTEM_PROMPT, user="\n".join(lines))


def render_draft(rule_ids: tuple[str, ...] | list[str], text: str) -> str:
    """把草稿渲染成契约要求的 JSON；:func:`parse_draft` 的逆运算。"""
    return json.dumps(
        {"rule_ids": list(rule_ids), "text": text},
        ensure_ascii=False,
    )


def parse_draft(raw: str, allowed_rule_ids: frozenset[str] | set[str]) -> Draft:
    """把模型输出解析成草稿，并把所有违约行为逐条记下来。

    这里**不抛异常**。抛异常会让调用方只剩下「整个失败」和「静默放行」两个
    选择，而正确做法是第三条路：把违约当作可披露的事实带下去，让 Critic
    把它变成用户看得见的意见。越界引用因此不会消失，只会被记名。
    """
    stripped = raw.strip()
    if not stripped:
        return Draft("", violations=("草稿为空。",))

    try:
        data = json.loads(_strip_fence(stripped))
    except json.JSONDecodeError as exc:
        return Draft(
            "",
            violations=(f"草稿不是合法 JSON：{exc.msg}（第 {exc.lineno} 行）。",),
        )

    if not isinstance(data, dict):
        return Draft(
            "",
            violations=(f"草稿顶层必须是 JSON 对象，实际是 {type(data).__name__}。",),
        )

    violations: list[str] = []
    extra = sorted(set(data) - set(DRAFT_KEYS))
    missing = sorted(set(DRAFT_KEYS) - set(data))
    if extra:
        violations.append(f"草稿含契约之外的字段：{'、'.join(extra)}。")
    if missing:
        violations.append(f"草稿缺少必需字段：{'、'.join(missing)}。")

    cited = _parse_rule_ids(data, allowed_rule_ids, violations)
    text = _parse_text(data, violations)
    return Draft(text, cited, tuple(violations))


def contract() -> dict[str, Any]:
    """把契约本身作为数据暴露出来，供 ``/api/llm/contract`` 审计。"""
    return {
        "version": CONTRACT_VERSION,
        "system_prompt": SYSTEM_PROMPT,
        "draft_schema": DRAFT_SCHEMA,
        "boundary": list(BOUNDARY_RULES),
        "forbidden_certainty_words": list(CERTAINTY_WORDS),
        "strength_marker": STRENGTH_MARKER,
        "low_strength_ceiling": LOW_STRENGTH_CEILING,
        "footnote": {
            "open": FOOTNOTE_OPEN,
            "close": FOOTNOTE_CLOSE,
            "pattern": FOOTNOTE_PATTERN.pattern,
            "required_for": "classical",
        },
        "notes": [
            "模型输入只有证据链；原始命盘与全量规则库不在签名里。",
            "越界引用不会被静默丢弃，会记入 violations 并由 Critic 披露。",
            "典籍规则的出处角标由 Critic 双向校验：该挂的挂了没有、挂的存不存在。",
            "本契约当前只由假 provider 驱动；真 provider 接线属于后续工作。",
        ],
    }


def _parse_rule_ids(
    data: dict[str, Any], allowed_rule_ids: frozenset[str] | set[str], violations: list[str]
) -> tuple[str, ...]:
    if "rule_ids" not in data:
        return ()
    raw_ids = data["rule_ids"]
    if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
        violations.append("rule_ids 必须是字符串数组。")
        return ()
    cleaned = [item.strip() for item in raw_ids]
    if any(not item for item in cleaned):
        violations.append("rule_ids 含空字符串。")
    unique = tuple(item for item in dict.fromkeys(cleaned) if item)
    for rule_id in unique:
        if rule_id not in allowed_rule_ids:
            violations.append(f"引用了证据链之外的规则 {rule_id}，已剔除。")
    return tuple(rule_id for rule_id in unique if rule_id in allowed_rule_ids)


def _parse_text(data: dict[str, Any], violations: list[str]) -> str:
    if "text" not in data:
        return ""
    body = data["text"]
    if not isinstance(body, str):
        violations.append(f"text 必须是字符串，实际是 {type(body).__name__}。")
        return ""
    if not body.strip():
        violations.append("text 为空。")
        return ""
    return body.strip()


def _strip_fence(text: str) -> str:
    """剥掉 Markdown 代码块围栏。

    这是唯一一处对模型输出的宽容处理：围栏是模型的书写习惯，不是内容。
    剥掉它不会放宽边界（边界在 ``rule_ids`` 校验上），除此之外一律严格。
    """
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def _jsonable(value: Any) -> Any:
    """把证据链里的值收敛成 JSON 能表达的形式。

    刻意不写 ``default=str`` 兜底：那会把无法序列化的值悄悄变成字符串，
    于是「证据链里混进了不该有的东西」表现成「提示词里多了一串乱码」。
    宁可在这里响亮地失败。
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(
        f"证据链里出现了无法序列化的值：{value!r}（类型 {type(value).__name__}）。"
    )
