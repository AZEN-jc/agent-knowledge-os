"""视觉回归：页面骨架的文本快照（Phase 5.9）。

## 为什么是文本快照而不是像素比对

像素比对（screenshot diff）在跨平台/跨字体环境里噪声极大：中文字体的
渲染差异足以让基线永远红，于是团队学会「重新生成基线」——那等于把
视觉回归关掉了。文本快照钉的是**骨架**：标签文字、标题、按钮名、
字段标签、声明文案。这些才是「有人不小心改了界面」的第一现场。

分析结果区（命盘/证据链/时间轴/典籍库）**不进快照** —— 它们的文本
随规则库增长合法变化，把它们钉死只会让快照变成噪声源。

## 更新方式

    UPDATE_SNAPSHOTS=1 python -m pytest tests/test_frontend_snapshot.py

更新必须在提交信息里说明为什么改（哪个标签变了、为什么），否则这条
测试会退化成「跑红了就重生成」的摆设。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="未安装 playwright")

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO / "tests" / "snapshots" / "frontend_chrome.txt"

#: 取页面骨架：剥掉 script/style，清空随数据变化的结果区，只留 chrome。
_CHROME_SCRIPT = """
() => {
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll("script, style").forEach((node) => node.remove());
  for (const id of ["chart", "analysis", "timeline-out", "library", "error"]) {
    const node = clone.querySelector("#" + id);
    if (node) node.textContent = "";
  }
  return clone.textContent
    .split("\\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .join("\\n");
}
"""


def test_frontend_chrome_matches_the_snapshot(browser, base_url):
    """browser/base_url 来自 tests/conftest.py；浏览器缺失时 fixture 自己 skip。"""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        actual = page.evaluate(_CHROME_SCRIPT)
    finally:
        context.close()

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(actual + "\n", encoding="utf-8")
        pytest.skip("快照已更新（UPDATE_SNAPSHOTS=1）")

    assert SNAPSHOT.is_file(), (
        f"缺视觉基线 {SNAPSHOT}。首次生成：UPDATE_SNAPSHOTS=1 python -m pytest "
        "tests/test_frontend_snapshot.py"
    )
    expected = SNAPSHOT.read_text(encoding="utf-8").rstrip("\n")
    if actual != expected:
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(), actual.splitlines(),
                fromfile="baseline", tofile="current", lineterm="",
            )
        )
        pytest.fail(
            "页面骨架与基线不一致。若是有意改动，用 UPDATE_SNAPSHOTS=1 重新生成"
            "并在提交信息里说明原因。差异：\n" + diff
        )
