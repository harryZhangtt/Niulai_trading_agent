# LangChain 架构参考笔记

参考：[《LangChain 与 LangGraph：从入门到实战超详解》](https://bytedance.larkoffice.com/docx/DER6dCHBhokjaVxB1d3cOatMnHb)。2026-11-15 通过 lark-cli 只读获取第 181 版，阅读了结构化输出、LangGraph 和实践建议章节。本笔记保留设计启发与核对结果，不复制文档全文。

## 文档把能力组合的接口讲清了

| 文档提供的机制 | 对本项目有用的判断 | 使用时保留的限制 |
| --- | --- | --- |
| Runnable 与明确的输入输出 | 先把数据获取、计算、coverage 等能力做成可独立调用和测试的单元，再组合流程。 | 普通函数已经足够的地方继续用函数，不必每个能力都建一个 Agent。 |
| StateGraph 的节点、状态更新和条件边 | 研究总图负责协调，固定的领域检查留在确定性节点，模型只参与需要判断或工具选择的部分。 | 总图不接管各组件的业务台账、证据准入或派发权限。 |
| 子图与状态映射 | 数据获取、研究分析和因子挖掘可以分别实现，通过 wrapper 交接有限结果。 | 子图共享检查点不等于共享所有业务字段。消息、预算和大体积数据继续按职责管理。 |
| Checkpointer、thread 与 interrupt | 将模型会话与业务状态分开，允许同一项任务等待回复、恢复或换用已配置的引擎。 | 检查点不证明外部调用可重放，也不替代原组件对 unknown 的处理。 |
| 结构化输出与流式事件 | 中间产物可以按 schema 校验，节点进度和错误可以逐步记录，便于定位调优变化。 | schema 合法不等于来源真实、研究完整或因子有效。具体输出和重试策略仍要按当前版本测试。 |

这些机制帮助确定如何组合与替换能力。原子能力先行、pipeline 的具体步骤为 TBD，以及观测评测先于业务迁移，是本项目在用户要求下作出的设计决定，并非教程已经替本项目给出的完整架构。

## 示例按当前版本重新核对

本地锁定依赖为 LangChain 1.5.0、LangGraph 1.2.22。当前安装源码中的 `create_agent` 返回编译后的 StateGraph，因此不能把它一概当作只会线性执行的链，再重复实现一遍模型工具循环。[官方 Agents 说明](https://docs.langchain.com/oss/python/langchain/agents)作为版本核对入口。

子图使用显式输入输出映射。并行结果先定义写入方、reducer 与去重规则，不把所有子流程的 messages 混成一份状态。[官方子图文档](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)支持按接口组合不同状态的子图。

结构化输出的可用策略取决于模型和适配器。不能直接继承教程中关于自动修复或重试的概括，当前会话引擎也没有因此获得所有 provider-native 能力。使用前按[官方结构化输出说明](https://docs.langchain.com/oss/python/langchain/structured-output)核对，并显式限制调用预算。

## 平台观测另以官方资料为准

LangSmith Agent Registry、prompt 管理、datasets 与 evaluator 的前置验收，来自用户追加的目标及本次另行核对的官方资料。教程中的流式事件和检查点只解释了其中一部分机制。

本地执行与云端可观测可以同时成立。先为现有 Agent 注册适用的平台身份，在 local 环境验证 tracing 和评测；以后需要托管执行时，再部署同一份代码。平台记录与代码里的 `create_agent` 是不同对象。[官方注册说明](https://docs.langchain.com/langsmith/create-an-agent)明确区分了它们。

后续参考入口：

- [Agent Registry 与环境](https://docs.langchain.com/langsmith/agent-registry)：先核对实际工作区模式及权限。
- [LangChain tracing](https://docs.langchain.com/langsmith/trace-with-langchain)：核验父子调用与实际证据的关联。
- [Prompt 管理](https://docs.langchain.com/langsmith/manage-prompts-programmatically)：固定实际使用的版本或 commit。
- [目标函数评测](https://docs.langchain.com/langsmith/evaluate-llm-application)：分别评估原子能力和完整 pipeline。

现阶段云端 tracing 仍关闭，平台接入与完整 pipeline 均未验收。计算器 E2E 的通过，只证明已经验证的模型与工具边界。阅读资料和写好方案，不能替代这些运行证据。

## 后续从这里继续

实施前先看[迁移方案](../plans/langchain-agent-migration.md)中的原子能力接口与前置门禁。涉及新 API、模型输出或子图恢复语义时，再核对锁定版本的源码和对应官方文档。引用本笔记时保留源文档版本，避免把后续修订误当作本次读到的内容。
