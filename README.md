# MingLi Agent（命理智能体）

**可验证的命理推理系统 · Verifiable Chinese Astrology Reasoning System**

---

## 项目定位

这不是一个"会算命的聊天机器人"，而是一个能够：
- ✅ **确定性排盘**（不让 LLM 算命盘）
- ✅ **规则引擎**（传统命理典籍规则化）
- ✅ **证据链追踪**（每个结论都有依据）
- ✅ **流派系统**（处理不同理论体系的冲突）
- ✅ **持续评估**（MingLi-Bench + fate-bench + 自建测试集）

的命理推理 Agent。

---

## 核心架构

```text
                         用户
                          ↓
                  Conversation Agent
                          ↓
         ┌────────────────┼────────────────┐
         ↓                ↓                ↓
    Chart Tools      Knowledge       User Memory
         ↓                ↓                ↓
   Bazi Engine      Classics Rules    Previous Q&A
         └────────────────┬────────────────┘
                          ↓
                   Evidence Layer  ★核心创新
                          ↓
                   Reasoning Agent
                          ↓
                    Critic Agent
                          ↓
                 Confidence / Conflict
                          ↓
                   Report Generator
```

---

## 为什么不是"LLM + 八字项目"

| 维度 | 普通AI算命 | MingLi Agent |
|------|-----------|--------------|
| **排盘** | LLM 计算 | 确定性引擎（HeiGe-SuanMing） |
| **推理** | 直接输出结论 | 证据链 + 规则引用 |
| **验证** | 无 | 三套 Benchmark |
| **流派** | 不区分 | 明确流派 + 冲突标注 |
| **可解释性** | 黑盒 | 全程可追溯 |
| **准确率** | 未知 | MingLi-Bench 持续监控 |

---

## 核心创新：Evidence Layer（证据层）

这是整个项目最重要的设计。

### 传统做法（错误）：
```text
命盘 → LLM → "你今年财运不错"
```

### MingLi Agent（正确）：
```text
命盘
 ↓
事实提取（月柱正官透出、日支与月支六合...）
 ↓
规则匹配（《滴天髓》RULE_017、《子平真诠》RULE_043...）
 ↓
证据链（事实 + 规则 + 来源）
 ↓
结论（基于以上证据，证据强度 0.68）
```

用户能清楚看到：
- 这个结论基于什么规则？
- 证据有多强？
- 不同流派怎么看？
- 哪些地方还不确定？

---

## 技术栈

### 排盘引擎
- **Python**：[HeiGe-SuanMing](https://github.com/HeiGeAi/HeiGe-SuanMing)（434个回归测试）
- **TypeScript**（前端）：[bazi-engine](https://github.com/openfate-ai/bazi-engine) / [shunshi-bazi-core](https://github.com/shunshi-ai/bazi-reader-mcp)

### 规则引擎
- Python + SQLite
- 经典文献：《渊海子平》《滴天髓》《子平真诠》《三命通会》《穷通宝鉴》

### 评估系统
- [MingLi-Bench](https://github.com/DestinyLinker/MingLi-Bench)（160道命理知识题）
- [fate-bench](https://github.com/shunshi-ai/fate-bench)（295个历史人物事件）
- 自建测试集（排盘、推理、幻觉检测）

### API 服务
- FastAPI
- LangChain / LlamaIndex（LLM 集成）
- PostgreSQL（用户数据）
- Redis（缓存）

### 前端
- React + TypeScript
- Tailwind CSS
- ECharts（命盘可视化）

---

## 执行计划

完整计划见 [MINGLI_PLAN.md](./MINGLI_PLAN.md)

### Phase 1-3：核心能力（2个月）
- [x] 调研 GitHub 优质项目
- [x] 制定完整执行计划
- [ ] 集成 HeiGe-SuanMing 排盘引擎
- [ ] 建立规则库（50+ 规则）
- [ ] 实现 Evidence Layer

### Phase 4-6：推理能力（2个月）
- [ ] Reasoning Agent
- [ ] Critic Agent（双模型架构）
- [ ] Time Engine（流年分析）

### Phase 7：评估体系（1个月）
- [ ] MingLi-Bench 集成
- [ ] fate-bench 集成
- [ ] 自建测试集（100+）

### Phase 8-10：产品化（2个月）
- [ ] 用户记忆系统
- [ ] Web UI
- [ ] RESTful API

### Phase 11-15：扩展能力
- [ ] 紫微斗数（基于 iztro）
- [ ] 流年详批
- [ ] 合婚分析
- [ ] 择吉系统
- [ ] MCP Server

### Phase 16-20：生产就绪
- [ ] 性能优化
- [ ] 安全加固
- [ ] 多语言支持
- [ ] 移动端
- [ ] 商业化

---

## 参考项目

### 排盘引擎
- [HeiGe-SuanMing](https://github.com/HeiGeAi/HeiGe-SuanMing) ⭐ 48 stars - 多引擎系统（八字+紫微+梅花+六爻+奇门），434个测试
- [openfate-ai/bazi-engine](https://github.com/openfate-ai/bazi-engine) - TypeScript，AI-ready
- [xuziping-bazi](https://github.com/mengke-wang/xuziping-bazi) ⭐ 45 stars - "先排盘、再开口"，严谨方法论
- [shunshi-ai/bazi-reader-mcp](https://github.com/shunshi-ai/bazi-reader-mcp) - MCP Server
- [houseme/lunar-rs](https://github.com/houseme/lunar-rs) - Rust 引擎

### 紫微斗数
- [SylarLong/iztro](https://github.com/SylarLong/iztro) ⭐ 454+ stars - 轻量级排盘库

### 评估系统
- [DestinyLinker/MingLi-Bench](https://github.com/DestinyLinker/MingLi-Bench) ⭐ 2,349 stars - 首个命理 LLM 评估基准
- [shunshi-ai/fate-bench](https://github.com/shunshi-ai/fate-bench) - 历史人物事件验证

---

## 设计原则

1. **计算与推理分离**：LLM 不负责计算，只负责理解问题和解释证据
2. **证据前置**：先有事实和规则，再有结论
3. **流派透明**：不同流派的判断差异必须明确告知用户
4. **可验证性**：每个阶段都有测试覆盖
5. **渐进式开发**：先八字，再紫微，再其他体系
6. **本地优先**：核心计算引擎可离线运行
7. **API 可替换**：不绑定单一 LLM 提供商

---

## 验收标准

每个 Phase 完成后必须输出：

1. 修改了什么
2. 为什么修改
3. 文件清单
4. 数据结构
5. API 文档
6. 测试结果
7. 构建结果
8. 已知问题
9. 未实现功能
10. 下一阶段建议

---

## 目标指标

| 指标 | 目标值（MVP） | 长期目标 |
|------|--------------|---------|
| MingLi-Bench 准确率 | > 40% | > 60% |
| fate-bench 命中率 | > 30% | > 50% |
| 排盘正确性 | 100% | 100% |
| 规则引用准确率 | > 95% | > 99% |
| 幻觉率 | < 5% | < 1% |
| 响应速度 | < 2s | < 1s |

---

## 风险与应对

### 技术风险
| 风险 | 应对 |
|------|------|
| LLM 幻觉 | 证据层约束 + Critic Agent |
| 规则冲突 | 流派系统明确标注 |
| 性能瓶颈 | 缓存 + 异步 + 索引 |
| 准确率不达标 | 持续优化规则库 + 更强 LLM |

### 产品风险
| 风险 | 应对 |
|------|------|
| 用户期望过高 | 明确说明是"推理工具"不是"预测工具" |
| 法律合规 | 免责声明 + 娱乐定位 |
| 商业化难 | 先做口碑，再做付费 |

---

## 安装与运行

```bash
# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 跑测试
pytest tests/

# 启动服务与 Web 界面（在仓库根目录执行）
python -m api.server
# 然后打开 http://127.0.0.1:8000
```

界面：输入生辰 → 看命盘、证据链（每条规则的条件与命盘出处、典籍原文与出处地址）、
审查结果、流年时间轴。接口文档在 `/docs`。

### 评估（回归门禁）

```bash
python evaluation/runner.py          # 人读报告
python evaluation/runner.py --json   # 机器可读
```

跑 10 个金标准案例 × 3 个主题，检查六条**系统行为不变量**：证据链不断环、
审查通过、结论不越界引用、不下确定性判断、强度在值域内、结果可复现。
退出码非 0 表示有未过项，可直接当门禁用。

评的不是「排盘准不准」—— 那已由 `tests/test_bazi_golden.py` 用 sxtwl 与
lunar-python **两套独立实现交叉确认**，比任何自建评估都严格。

### 多主题并发分析

`POST /api/analyze/multi` 一次分析多个主题，服务端并发执行。命盘只算一次，
扇出点在它之后；单个主题失败不影响其余，失败项以 `ok=false` 如实带回原因。

---

## 已知边界

- **大运需要性别**。顺逆规则不同流派有分歧，缺性别时只算流年、不猜默认方向。
  启用后结果带 `approximate: true`（三日折一年）。
- **LLM provider 未接线**。默认走确定性模板出稿，离线可运行；契约见
  `GET /api/llm/contract`。要接真 provider 就注入一个，接口只有
  `complete(request) -> str`。
- **典籍层只覆盖《三命通會》卷八「六甲日甲子時斷」**（13 条）。其余条目
  被阻塞在「拿到可核验底本」这一步，见 `GET /api/classics/backlog`。
- **紫微斗数排盘引擎未做**。`engines/` 下只有 `bazi/`；没有引擎，那批规则
  的条件无处落地。底本已固化挂 `role=reserve`，等引擎到位。

---

## 贡献指南

欢迎贡献：

1. **规则库**：补充传统命理典籍的规则
2. **测试用例**：提供边界 case 和 golden case
3. **流派系统**：补充不同流派的理论
4. **文档**：完善使用文档和 API 文档
5. **Bug 修复**：报告和修复问题

---

## 许可证

MIT License

---

## 联系方式

- GitHub Issues：问题反馈
- Discussions：技术讨论

---

## 致谢

感谢以下项目的启发和参考：

- HeiGe-SuanMing：完整的多引擎系统和知识底座
- MingLi-Bench：首个命理 LLM 评估基准
- fate-bench：历史人物事件验证数据
- bazi-engine / iztro：现代化的排盘引擎实现

---

**当前状态**：Phase 0 规划完成，准备进入 Phase 1 排盘引擎集成。

**下一步**：集成 HeiGe-SuanMing，建立排盘引擎测试框架。
