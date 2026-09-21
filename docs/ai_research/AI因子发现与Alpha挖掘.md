# AI Alpha 与因子发现

## 1. Alpha-GPT

标题：Alpha-GPT: Human-AI Interactive Alpha Mining for Quantitative Investment

- 年份：2023
- 公开链接：[arXiv 2308.00016](https://arxiv.org/abs/2308.00016)
- DOI：[10.48550/arxiv.2308.00016](https://doi.org/10.48550/arxiv.2308.00016)
- 关键词：human-AI interaction、alpha mining、quantitative investment、formulaic alpha

资料要点：

- 人类提供投资直觉、市场观点或研究方向。
- LLM 将自然语言想法转成候选因子或公式表达式。
- 量化模块负责计算、回测和评价候选表达式。
- 回测结果再次反馈给人和模型，形成多轮研究循环。
- 重点不是让 LLM 直接给出股票，而是让 LLM 参与 Alpha 假设生成和表达式构造。

对研究的启发：这是目前最接近“通过对话选择因子”的公开研究路线。

## 2. Alpha-GPT 2.0

标题：Alpha-GPT 2.0: Human-in-the-Loop AI for Quantitative Investment

- 年份：2024
- 公开链接：[arXiv 2402.09746](https://arxiv.org/abs/2402.09746)
- DOI：[10.48550/arxiv.2402.09746](https://doi.org/10.48550/arxiv.2402.09746)

资料要点：

- 延续人机协同 Alpha 挖掘路线。
- 更强调人类反馈、候选搜索、量化评估和组合形成之间的闭环。
- 可作为设计“用户提出想法 -> Agent 生成候选 -> 用户确认 -> 回测 -> 继续优化”流程的直接参考。

## 3. Alpha-GPT EMNLP Demo

标题：Alpha-GPT: Human-AI Interactive Alpha Mining for Quantitative Investment

- 年份：2025
- 公开链接：[ACL Anthology 2025 EMNLP Demo](https://aclanthology.org/2025.emnlp-demos.14/)
- DOI：[10.18653/v1/2025.emnlp-demos.14](https://doi.org/10.18653/v1/2025.emnlp-demos.14)

资料要点：

- 更适合参考交互式演示系统和用户界面形态。
- 适合关注系统如何展示候选因子、反馈和研究结果。

## 4. AlphaForge

标题：AlphaForge: A Framework to Mine and Dynamically Combine Formulaic Alpha Factors

- 年份：2025
- 公开链接：[AAAI DOI 页面](https://doi.org/10.1609/aaai.v39i12.33365)
- PDF：[AAAI PDF](https://ojs.aaai.org/index.php/AAAI/article/download/33365/35520)
- DOI：10.1609/aaai.v39i12.33365

资料要点：

- 关注公式化 Alpha 的挖掘。
- 不只生成单个因子，还关注多个因子的动态组合。
- 适合研究因子去重、候选筛选、组合和因子有效性变化。

## 5. AlphaAgent

标题：AlphaAgent: LLM-Driven Alpha Mining with Regularized Exploration to Counteract Alpha Decay

- 年份：2025
- 公开链接：[ACM DOI 页面](https://doi.org/10.1145/3711896.3736838)
- DOI：10.1145/3711896.3736838

资料要点：

- 关注 LLM 驱动的 Alpha 搜索。
- 明确讨论 Alpha 衰减问题。
- 重点方向是探索控制、候选搜索正则化和避免过度重复或过度拟合。

## 6. 与传统因子研究的关系

这些研究并没有消除传统量化研究的基本问题：

- 因子是否有经济机制；
- 数据在当时是否可得；
- 是否存在前视偏差；
- 是否只是大量试验后挑出的幸运结果；
- 样本外是否稳定；
- 交易成本和容量是否可接受。

因此，AI Alpha 研究应被理解为“研究搜索和交互方式的变化”，而不是“统计验证规则的消失”。
