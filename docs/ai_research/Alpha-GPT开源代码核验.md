# Alpha-GPT 开源代码核验

## 核验对象

### 论文版本

- [Alpha-GPT: Human-AI Interactive Alpha Mining for Quantitative Investment](https://arxiv.org/abs/2308.00016)
- [Alpha-GPT 2.0: Human-in-the-Loop AI for Quantitative Investment](https://arxiv.org/abs/2402.09746)
- [Alpha-GPT: Human-AI Interactive Alpha Mining, EMNLP Demo](https://aclanthology.org/2025.emnlp-demos.14/)

## 当前结论

截至 2026-08-14，**没有核实到由 Alpha-GPT 论文作者明确发布的官方 GitHub 开源仓库**。

更准确的说法是：

> 论文和公开演示页面可以访问，但目前没有找到可确认属于作者团队的完整官方代码仓库，因此不能把网上同名或相似项目称为 Alpha-GPT 官方实现。

## 已检查内容

- arXiv 论文页面：有论文、PDF、作者和版本信息，没有明确的 GitHub 代码链接。
- Alpha-GPT EMNLP Demo 页面：有论文和 PDF 信息，没有明确的作者代码仓库链接。
- 论文页面中的代码聚合入口：未核实到可用的 Alpha-GPT 官方仓库。
- GitHub 公开搜索：触发 GitHub secondary rate limit，因此不能据此证明 GitHub 上不存在同名仓库。

## 因此如何使用

- 可以把 Alpha-GPT 当作方法论和系统设计参考。
- 不应直接声称“Alpha-GPT 有官方开源代码”。
- 网上可能存在第三方复现、同名项目或基于论文思想的实现，但需要逐一核对作者、组织和论文关联。
- 如果根据论文在当前项目中实现自然语言到因子表达式、回测反馈和人机循环，那属于自行复现，不是官方代码。

## 可替代参考

如果目的是寻找可以直接运行或阅读的相近代码，可先看：

- [TradingAgents](https://github.com/TauricResearch/TradingAgents)：多 Agent 金融交易框架；
- [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)：金融 Agent 平台；
- [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund)：开源演示型多 Agent 投研项目；
- [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent)：自动化研发和数据科学研究 Agent；
- [Microsoft Qlib](https://github.com/microsoft/qlib)：量化研究和回测基础设施。

这些项目都不是 Alpha-GPT 官方实现，只是相关方向的公开参考。
