"""新增一条典籍原子的收口清单：四处必须同步动，以及见证盘的建议。

**为什么要这个脚本。** 往 ``atoms/`` 里加一条原子，改动不止那一处。若引入了
新的条件键，要同步动的地方有四个：

1. ``atoms/*.json`` —— 原子本身（URN、引文、条件、转述）
2. ``knowledge/facts.py`` —— 事实提取，新键要有产出
3. ``tests/test_evidence_audit.py`` 的 ``audit_fact_map`` —— 独立复核
4. ``tests/test_structural_rules.py`` 的 ``RULE_WITNESS`` —— 见证命盘

四处里后三处都在**测试文件**里，而改原子的人盯着的往往是第一个。漏掉的代价
是一次全量跑（四分钟）换来两条语义不明的红测试，再靠反推找出缺的是哪一处。
这个脚本把那四处的状态一次性摆出来，直接说「缺什么、加在哪」。

**它不替代测试。** 测试是断言，这个脚本是诊断视图：测试说「坏了」，脚本说
「这是你要补的东西」。两者的实现刻意共用同一份 ``audit_fact_map`` ——
重新实现一遍只会漂移。

用法::

    python scripts/atom_checklist.py                      # 四处状态一览
    python scripts/atom_checklist.py --suggest-witness RULE_ID
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
# 测试目录也要进 sys.path —— 下面两个 ``test_*`` 模块是被**故意**复用的：
# ``audit_fact_map`` 的价值全在它是一条独立于 ``knowledge.facts`` 的实现路径，
# 脚本里另写一份等于把两条路径并成一条，复核也就没了。
sys.path.insert(0, str(REPO / "tests"))

from test_evidence_audit import audit_fact_map
from test_structural_rules import RULE_WITNESS, WITNESS_ALSO_MATCHES

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.facts import FACT_SCHEMA, extract_facts, group_facts
from knowledge.provenance import SourceTier

PROVIDER = SxtwlBaziProvider()

# 事实键观察用的抽样盘。刻意跨多个年月与日干日支，让冷僻键也有机会露面 ——
# 观察不到不等于没产出（``repeated_branches`` 在多数盘上就是空的），所以
# 状态栏对观察不到的键报「未观察到」而不是「缺失」。
PROBE_BIRTHS: tuple[tuple[int, int, int, int], ...] = (
    (1951, 1, 4, 0), (1950, 9, 6, 0), (1956, 10, 4, 0), (1958, 3, 28, 0),
    (1990, 2, 1, 12), (1990, 1, 9, 14), (1984, 6, 15, 6), (2000, 12, 25, 23),
    (1975, 8, 8, 10), (2010, 5, 20, 4), (1940, 11, 11, 11), (2030, 7, 7, 7),
)


def classical_rules() -> list:
    return list(default_registry().select(source_tier=SourceTier.CLASSICAL))


def chapter_of(rule_id: str) -> str | None:
    for rule in classical_rules():
        if rule.id == rule_id and rule.citation is not None:
            urn = rule.citation.parsed_urn
            return f"{urn.juan}.{urn.chapter}"
    return None


def observed_fact_keys() -> set[str]:
    """抽样盘上实际出现过的键。"""
    seen: set[str] = set()
    for birth in PROBE_BIRTHS:
        # ``extract_facts`` 产出的是 Fact 对象，键在 ``.type`` 上 —— 不是字典键。
        seen |= {fact.type for fact in extract_facts(PROVIDER.calculate(BirthInput(*birth)))}
    return seen


def audited_fact_keys() -> set[str]:
    seen: set[str] = set()
    for birth in PROBE_BIRTHS:
        seen |= set(audit_fact_map(PROVIDER.calculate(BirthInput(*birth))))
    return seen


def status() -> int:
    """打印四处状态。有未完成项时返回 1。"""
    rules = classical_rules()
    registry_keys = default_registry().condition_keys()
    emitted = observed_fact_keys()
    audited = audited_fact_keys()

    print("事实键（规则读取 → 词表 → 提取 → 独立复核）")
    print("-" * 62)
    outstanding_keys = 0
    for key in sorted(registry_keys):
        in_schema = key in FACT_SCHEMA
        in_extract = key in emitted
        in_audit = key in audited
        if in_schema and in_extract and in_audit:
            continue
        outstanding_keys += 1
        # 词表里都没有是最严重的一档：规则引用了一个不存在的事实。
        # 提取或复核没观察到可能是抽样问题，只作提示。
        missing = []
        if not in_schema:
            missing.append("词表无此键")
        if not in_extract:
            missing.append("提取未观察到")
        if not in_audit:
            missing.append("复核未覆盖")
        print(f"  {key:<34} {'、'.join(missing)}")

    print(f"  共 {len(registry_keys)} 个条件键，{outstanding_keys} 个待处理")

    print()
    print("见证命盘")
    print("-" * 62)
    missing_witness = sorted({r.id for r in rules} - set(RULE_WITNESS))
    for rule_id in missing_witness:
        print(f"  {rule_id}")
    print(f"  共 {len(rules)} 条典籍规则，{len(missing_witness)} 条缺见证盘")

    print()
    print("重叠登记（WITNESS_ALSO_MATCHES 复核）")
    print("-" * 62)
    stale = []
    for rule_id, also in sorted(WITNESS_ALSO_MATCHES.items()):
        birth = RULE_WITNESS.get(rule_id)
        if birth is None:
            # 见证盘还没补，而登记表已经写了这条 —— 上面那节会报「缺见证盘」，
            # 这里不再重复报，否则同一次疏漏被数成两件事。
            continue
        year, month, day, hour = birth
        matched = default_registry().match(
            extract_facts(PROVIDER.calculate(BirthInput(year, month, day, hour)))
        )
        got = {m.rule.id for m in matched}
        if not also <= got:
            stale.append(rule_id)
            print(f"  {rule_id} 登记了不再发生的重叠")
    print(f"  共 {len(WITNESS_ALSO_MATCHES)} 条登记，{len(stale)} 条过期")

    done = outstanding_keys == 0 and not missing_witness and not stale
    print()
    print("全部就绪。" if done else "有未完成项，见上。")
    return 0 if done else 1


#: 时支 → 一个落在该时辰内的钟点。找见证盘要按原子的时柱取时辰，
#: 而不是一律按 0 点扫：11/12 的原子时柱不是子时，只扫 0 点会让它们
#: 全部「90 年里没有命盘能命中」。子时取 0 点（早子时），与 provider 的
#: 默认晚子时口径一致（23 点才涉及换日，这里不碰边界）。
HOUR_OF_BRANCH = {
    "子": 0, "丑": 2, "寅": 4, "卯": 6, "辰": 8, "巳": 10,
    "午": 12, "未": 14, "申": 16, "酉": 18, "戌": 20, "亥": 22,
}


def _day_pillar_of(date: dt.date) -> tuple[str, str]:
    """只算日柱，用来快速跳过不相干的日子。

    完整排盘要算节气、十神、关系，一次几百微秒；90 年 × 365 天全算一遍
    是分钟级。先用一次 ``sxtwl.fromSolar().getDayGZ()`` 过滤，只有日柱
    对上的那 1/60 天才走完整流程。
    """
    import sxtwl

    day = sxtwl.fromSolar(date.year, date.month, date.day)
    gz = day.getDayGZ()
    return "甲乙丙丁戊己庚辛壬癸"[gz.tg], "子丑寅卯辰巳午未申酉戌亥"[gz.dz]


def suggest_witness(rule_id: str, years: int, want: int, hour: int | None = None) -> int:
    """扫日期找见证盘：命中该规则、且同组内重叠最少的排前面。

    ``hour`` 缺省时按规则条件里的 ``hour_branch`` 推一个钟点；显式传入
    则用传入值（人工复核时用）。
    """
    rule = next((r for r in classical_rules() if r.id == rule_id), None)
    if rule is None:
        print(f"没有这条典籍规则：{rule_id}", file=sys.stderr)
        return 2

    condition = rule.condition
    target_day = (condition.get("day_stem"), condition.get("day_branch"))
    if hour is None:
        hour = HOUR_OF_BRANCH.get(str(condition.get("hour_branch", "子")), 0)

    mine = chapter_of(rule_id)
    same_group = {
        r.id for r in classical_rules() if r.citation is not None and chapter_of(r.id) == mine
    }
    taken = {r for r in same_group if r in RULE_WITNESS}
    print(f"规则 {rule_id}")
    print(f"条件 {rule.condition}")
    print(f"同组（{mine}）已有见证盘的 {len(taken)} 条：{sorted(taken)}")
    print(f"按日柱 {''.join(str(part) for part in target_day if part)} / {hour} 点扫描…",
          flush=True)

    # 注册表与 provider 都必须在循环外建。``default_registry()`` 每次调用都会
    # 重新读语料、重放守卫；放在循环里等于每张盘重读一遍底本，扫 90 年直接
    # 拖到超时。命盘也只算一次 —— 匹配与事实抽取共用同一张。
    registry = default_registry()
    start = dt.date(1940, 1, 1)
    end = start + dt.timedelta(days=365 * years)
    found: list[tuple[int, tuple[int, int, int, int], tuple, tuple]] = []
    # 扫描游标叫 ``cursor`` 而不是 ``day``：下面解包候选时 ``day`` 是**日号整数**，
    # 同名复用会让 mypy 报「int 赋给 date」——那是真会看错的地方，改名字而不是
    # 加 type: ignore。
    cursor = start
    while cursor < end and len(found) < want * 8:
        if target_day[0] and _day_pillar_of(cursor) != (target_day[0], target_day[1]):
            cursor += dt.timedelta(days=1)
            continue
        chart = PROVIDER.calculate(BirthInput(cursor.year, cursor.month, cursor.day, hour))
        got = {match.rule.id for match in registry.match(extract_facts(chart))}
        if rule_id in got:
            facts = group_facts(extract_facts(chart))
            extra = tuple(sorted(same_group & got - {rule_id}))
            found.append((len(extra), (cursor.year, cursor.month, cursor.day, hour), extra,
                          (facts.get("month_pillar"), facts.get("day_pillar"))))
        cursor += dt.timedelta(days=1)

    if not found:
        print(f"{years} 年里没有命盘能命中这条规则 —— 条件可能写错了，"
              "或者它依赖的事实在扫描范围内不出现。")
        return 1

    found.sort(key=lambda item: (item[0], item[1]))
    print()
    print("候选（重叠最少在前）：")
    for count, (year, month, day, hour), extra, pillars in found[:want]:
        note = "仅命中本条" if not extra else f"另命中 {list(extra)}"
        print(f"  {year}-{month:02d}-{day:02d} {hour}时  月柱 {pillars[0]} 日柱 {pillars[1]}  {note}")
    print()
    print("挑一张写进 RULE_WITNESS。若它必然多命中同组其它规则，"
          "把那条同时写进 WITNESS_ALSO_MATCHES 并注明理由。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suggest-witness", metavar="RULE_ID", help="为这条规则找见证盘")
    parser.add_argument("--years", type=int, default=90, help="扫描年数，默认 90")
    parser.add_argument("--want", type=int, default=5, help="给出几个候选，默认 5")
    parser.add_argument(
        "--hour", type=int, default=None,
        help="按哪个钟点找见证盘；缺省时由规则的时支推算",
    )
    args = parser.parse_args()

    if args.suggest_witness:
        return suggest_witness(args.suggest_witness, args.years, args.want, args.hour)
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
