"""变异探针：撤掉关键守卫，看测试会不会变红。

## 为什么需要这个脚本

绿测试有两种：**真的守住了**，和**恰好没被踩到**。二者的区别在代码被改坏时
才显形 —— 而那时往往已经上线。变异测试的做法是主动把守卫改坏一处，
看有没有测试立刻失败；没有，就说明那块地方其实没人守。

## 纪律（来自本项目的踩坑记录）

1. **先验基线干净。** 基线本来就红的时候，「抓住变异」毫无意义 ——
   测试可能因为别的原因失败。所以脚本第一步先跑一遍全部目标测试文件，
   不全绿就拒绝继续。
2. **一次只改一处，改完立刻还原。** 还原放在 ``finally`` 里，并在结束时
   用哈希核对文件内容与开始时逐字节相同。
3. **锚点找不到也算失败。** 变异脚本靠字符串匹配定位代码；代码重构后锚点
   失效，脚本会「什么都没改却报告全部被抓」—— 那是假通过。所以锚点缺失
   单独算一条错误。

## 用法

::

    python scripts/mutation_probe.py            # 人类可读
    python scripts/mutation_probe.py --json     # 机器可读

退出码 0 表示每个变异都被至少一条测试抓住；非 0 表示有变异存活（测试有洞）
或脚本自身出错。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@dataclass(frozen=True)
class Mutation:
    """一处「把守卫改坏」的变异。"""

    id: str
    guard: str
    """被撤掉的守卫叫什么（写给人看）。"""
    path: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1",
        guard="节气边界左闭：节时刻当刻属于新的一月",
        path="engines/bazi/jieqi.py",
        old="candidates = [term for term in terms if term.moment <= instant]",
        new="candidates = [term for term in terms if term.moment < instant]",
        tests=("tests/test_time_boundaries.py",),
    ),
    Mutation(
        id="M2",
        guard="历法换算一律走公历（不按 1582 分支）",
        path="engines/bazi/jieqi.py",
        old="    alpha = int((z - 1867216.25) / 36524.25)\n    a = z + 1 + alpha - int(alpha / 4)",
        new=(
            "    alpha = int((z - 1867216.25) / 36524.25)\n"
            "    a = z + 1 + alpha - int(alpha / 4) if z >= 2299161 else z"
        ),
        tests=("tests/test_jieqi_calendar.py",),
    ),
    Mutation(
        id="M3",
        guard="超出 datetime 范围的节气项被丢弃",
        path="engines/bazi/jieqi.py",
        old="        if not MIN_YEAR <= year_ <= MAX_YEAR:\n            continue",
        new="        if False:\n            continue",
        tests=("tests/test_jieqi_calendar.py",),
    ),
    Mutation(
        id="M4",
        guard="日柱天干不当十神（不产出「日主」）",
        path="knowledge/facts.py",
        old='        if pillar.name != "day" and pillar.ten_god:',
        new="        if pillar.ten_god:",
        tests=("tests/test_fact_consistency.py",),
    ),
    Mutation(
        id="M5",
        guard="容器×容器按交集判断",
        path="knowledge/rules.py",
        old=(
            "    if actual_is_many and expected_is_many:\n"
            "        # 两侧都是集合语义：只要有一项对得上即成立。\n"
            "        return bool(set(actual) & set(expected))"
        ),
        new=(
            "    if actual_is_many and expected_is_many and False:\n"
            "        return bool(set(actual) & set(expected))"
        ),
        tests=("tests/test_rule_governance.py",),
    ),
    Mutation(
        id="M6",
        guard="典籍断语进入 ACTIVE 前必须有可核验引文",
        path="knowledge/rules.py",
        old="        if self.review_status is not ReviewStatus.ACTIVE:\n            return",
        new="        if True:\n            return",
        # 守卫的测试在 test_provenance.py（Rule 构造期），不在 corpus 那组。
        # 第一版指到 test_corpus_citation.py，报「存活」—— 那是目标选窄了，
        # 不是真漏洞。这也是下面「存活时用全套复验」那道兜底存在的原因。
        tests=("tests/test_provenance.py", "tests/test_corpus_citation.py"),
    ),
    Mutation(
        id="M7",
        guard="规则版本号格式收口",
        path="knowledge/rules.py",
        old="        if not VERSION_PATTERN.match(self.version):",
        new="        if False:",
        tests=("tests/test_rule_governance.py",),
    ),
    Mutation(
        id="M8",
        guard="强度用凹饱和（永远到不了 1）",
        path="knowledge/evidence.py",
        old="    after = raw / (raw + SATURATION_K) if raw else 0.0",
        new="    after = raw / SATURATION_K if raw else 0.0",
        tests=("tests/test_evidence_strength.py",),
    ),
    Mutation(
        id="M9",
        guard="底本哈希不符必须报出来",
        path="knowledge/corpus.py",
        old="            if actual != entry.text_sha256:",
        new="            if False:",
        tests=("tests/test_corpus_citation.py",),
    ),
    Mutation(
        id="M10",
        guard="起运按三日折一年",
        path="engines/bazi/time_engine.py",
        old="DAYS_PER_YEAR = 3.0  # 三日折一年",
        new="DAYS_PER_YEAR = 4.0  # 三日折一年",
        tests=("tests/test_time_engine.py",),
    ),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(tests: tuple[str, ...]) -> tuple[int, str]:
    """跑一批测试文件，返回（退出码, 末尾输出）。

    **不用仓库目录当 cwd。** 本机沙箱下，以仓库为 cwd 时 pytest 的
    ``tmp_path`` 会落在不可写的位置，``test_corpus_citation.py`` 里用
    ``tmp_path`` 的 26 条会全部 PermissionError —— 而那是夹具问题，不是被测
    代码的问题，却会让基线检查误判成「基线不干净」。改成在 ``/tmp`` 下跑、
    用 ``--rootdir`` 指定仓库根（``pythonpath = ["."]`` 按 rootdir 解析），
    ``--basetemp`` 也放到 ``/tmp``。
    """
    completed = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            *(str(REPO / test) for test in tests),
            "-q", "-p", "no:cacheprovider", "--no-header",
            f"--rootdir={REPO}",
            "--basetemp=/tmp/ako-mutation",
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
    )
    tail = (completed.stdout + completed.stderr).strip().splitlines()
    return completed.returncode, "\n".join(tail[-3:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()

    all_tests = tuple(sorted({test for mutation in MUTATIONS for test in mutation.tests}))

    # ── 第一步：基线必须干净 ────────────────────────────────────────
    baseline_code, baseline_tail = run_pytest(all_tests)
    if baseline_code != 0:
        message = (
            "基线不干净，拒绝做变异探针。\n"
            f"命令：pytest {' '.join(all_tests)}\n退出码：{baseline_code}\n{baseline_tail}"
        )
        print(message, file=sys.stderr)
        return 2

    originals = {mutation.path: digest(REPO / mutation.path) for mutation in MUTATIONS}
    results: list[dict[str, object]] = []
    problems: list[str] = []

    for mutation in MUTATIONS:
        path = REPO / mutation.path
        source = path.read_text(encoding="utf-8")
        if source.count(mutation.old) != 1:
            problems.append(
                f"{mutation.id} 的锚点在 {mutation.path} 里出现 "
                f"{source.count(mutation.old)} 次（应为 1）—— 代码变了，锚点需要更新"
            )
            results.append({
                "id": mutation.id, "guard": mutation.guard,
                "status": "anchor_missing", "detail": "锚点不唯一或不存在",
            })
            continue

        try:
            path.write_text(source.replace(mutation.old, mutation.new, 1), encoding="utf-8")
            code, tail = run_pytest(mutation.tests)
        finally:
            path.write_text(source, encoding="utf-8")

        caught = code != 0
        detail = tail if caught else "撤掉守卫后目标测试仍然全绿"
        status = "caught" if caught else "SURVIVED"

        if not caught:
            # 目标文件没抓住时，用全套复验一次再下结论。
            #
            # **这一步是必需的，不是保险。** 探针只证明「指定的测试文件抓住了
            # 它」，不证明「没人抓住它」—— 守卫的测试可能落在别的文件里
            # （M6 就真的踩过：测试在 test_provenance.py，第一版指到了
            # test_corpus_citation.py）。不做这步就会把「目标选窄」误报成
            # 「测试有洞」，而假警报会让整个探针失去可信度。
            full_code, full_tail = run_pytest(("tests",))
            if full_code != 0:
                status = "caught_elsewhere"
                detail = "目标文件没抓住，但全套能抓住 —— 应把目标文件补进 tests"
            else:
                detail = "撤掉守卫后**全套**测试仍然全绿"
                tail = full_tail

        results.append({
            "id": mutation.id,
            "guard": mutation.guard,
            "status": status,
            "detail": detail if status != "caught" else tail,
        })

    # ── 还原核对 ────────────────────────────────────────────────────
    for relative, original_digest in originals.items():
        if digest(REPO / relative) != original_digest:
            problems.append(f"{relative} 未被还原到原始内容")

    survived = [item for item in results if item["status"] == "SURVIVED"]
    elsewhere = [item for item in results if item["status"] == "caught_elsewhere"]
    payload = {
        "total": len(MUTATIONS),
        "caught": len([item for item in results if item["status"] == "caught"]),
        "survived": len(survived),
        "caught_elsewhere": len(elsewhere),
        "anchor_missing": len([item for item in results if item["status"] == "anchor_missing"]),
        "results": results,
        "problems": problems,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"变异探针 · {payload['total']} 处变异，基线干净")
        print("-" * 72)
        marks = {
            "caught": "抓住",
            "caught_elsewhere": "别处抓",
            "SURVIVED": "存活",
            "anchor_missing": "锚点失效",
        }
        for item in results:
            print(f"{item['id']:<4} {marks[str(item['status'])]:<6} {item['guard']}")
            if item["status"] != "caught":
                print(f"      {item['detail']}")
        print("-" * 72)
        print(
            f"抓住 {payload['caught']}/{payload['total']}，"
            f"别处抓住 {payload['caught_elsewhere']}，"
            f"存活 {payload['survived']}，锚点失效 {payload['anchor_missing']}"
        )
        for problem in problems:
            print(f"  ! {problem}")

    return 0 if not survived and not problems and not elsewhere else 1


if __name__ == "__main__":
    raise SystemExit(main())
