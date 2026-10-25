"""隐私声明的可核验性（Phase 5.8）。

## 这个文件守什么

隐私声明最容易腐烂的方式不是「说错」，是「说过时」：代码把缓存上限
从 256 改成 512，文档与页面还写着 256，谁也没发现。这类数字必须能被
机器对上，否则声明只是历史遗迹。

三条断言：

1. 页面上的声明必须在（用户不会去读 docs/，看得见是底线）；
2. 页面与文档里的缓存上限，必须等于 ``agents.mingli.RESPONSE_CACHE_LIMIT``；
3. 文档必须写明部署侧的边界（日志由部署方决定）—— 承诺到哪为止要说清。
"""

from __future__ import annotations

import re
from pathlib import Path

from agents.mingli import RESPONSE_CACHE_LIMIT

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "static" / "index.html"
POLICY = REPO / "docs" / "reports" / "phase5-8-privacy-retention.md"


def _page() -> str:
    return INDEX.read_text(encoding="utf-8")


# ── 页面上的声明 ───────────────────────────────────────────────────────


def test_page_states_the_three_privacy_facts():
    page = _page()

    assert 'id="privacy"' in page, "页面缺隐私声明区"
    for claim in ("不存储", "内存缓存", "导出与日志"):
        assert claim in page, f"隐私声明缺「{claim}」"
    # 三条的具体内容：无账号/无数据库；缓存进程退出即清空；请求体不记录。
    assert "无账号" in page and "无数据库" in page
    assert "进程退出即清空" in page
    assert "不记录请求体" in page


def test_page_cache_number_matches_the_code_constant():
    """页面写的缓存上限必须等于代码里的常量。"""
    page = _page()
    match = re.search(r'id="cache-limit">(\d+)<', page)
    assert match, "页面里找不到缓存上限的标注"
    assert int(match.group(1)) == RESPONSE_CACHE_LIMIT


# ── 文档与代码一致 ─────────────────────────────────────────────────────


def test_policy_document_exists_and_states_the_same_number():
    assert POLICY.is_file(), "缺保留策略文档"
    text = POLICY.read_text(encoding="utf-8")

    assert str(RESPONSE_CACHE_LIMIT) in text, (
        f"文档没写缓存上限 {RESPONSE_CACHE_LIMIT}，或写了别的数"
    )


def test_policy_document_draws_the_deployment_boundary():
    """文档必须写明「部署方另加日志不归本项目管」—— 承诺的边界要看得见。"""
    text = POLICY.read_text(encoding="utf-8")

    assert "部署方" in text
    assert "请求体" in text


def test_policy_document_describes_the_cache_honestly():
    """缓存的说法必须两头都不含糊：不是「没有用户数据」，也不是「存了生辰」。

    文档要说清缓存键的构成（提示词/证据链，不含原始生辰字段），
    否则声明要么夸大安全、要么制造恐慌。
    """
    text = POLICY.read_text(encoding="utf-8")

    assert "提示词" in text
    assert "不含" in text and "生辰" in text


def test_policy_document_has_no_retention_period_claim():
    """没有持久化就不该编一个「保留 N 天」—— 那是无中生有的承诺。"""
    text = POLICY.read_text(encoding="utf-8")

    assert "无「保留期」概念" in text or "保留期" in text
