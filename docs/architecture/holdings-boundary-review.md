# 持仓获取与组合管理边界

2026-11-15，子代理只读检查了与持仓相关的源码和契约。没有调用 provider、读取真实账户 payload、访问凭证、运行账户测试或修改归档。以下是当前工作区源码审查，不能替代实际持仓获取或生产验收。

## 维护入口已经存在

`niulai-private/README_PRIVATE.md` 把该目录定义为原始备份。对归档 `state/portfolio_bundle.zip` 中选定代码的逐字节对照显示，`analytics.py`、`position_totals.py`、`daily_performance.py` 和 `daily_compact_pipeline.py` 与 `niulai/holdings/` 对应文件一致。归档中的 `niulai_tiger.py` 与维护副本第 1–592 行一致，维护副本随后增加了报价 helper。检查未打开归档中的账户 JSON 或历史 fixture。

持仓读取的维护入口是 `shared/tiger`，`niulai-runtime/niulai_runtime/tiger.py` 只是兼容入口。`positions`、`assets` 和 `snapshot` 不接受任意账户 ID 或写操作，并要求实际观察到唯一的 STANDARD 账户，见 `shared/tiger/queries.py` 的范围检查。运行时无需从私有归档恢复一份新的持仓服务。

## 读取、分析和执行分别验收

| 能力 | 已有依据 | 接入边界 |
| --- | --- | --- |
| 获取快照 | `shared/tiger/queries.py` 的 positions、assets 和 snapshot | Gateway 管理凭证、租约、token checkpoint、私有产物和不确定结果的核对。 |
| 组合分析 | `niulai/holdings/analytics.py:49` 的 `build(holdings, assets, taxonomy)`，以及独立的收益来源检查 | 显式适配账户／币种范围，计算集中度、敞口、NAV／现金等结果。它不是持仓修改服务。 |
| 管理建议 | 归档研究方法中的持有、增减仓和退出讨论，以及 opportunity-cost policy | 研究和 entry policy 提供证据，结果保持建议，不授权修改账户或下单。 |
| 本地记录修改 | 已有 alert CRUD 和 research store 各自的版本、请求身份与回读机制 | 这些接口不能冒充通用 holdings CRUD。需要持仓记录修改时，另行定义所属模块与契约。 |
| 券商执行 | 本次审查没有发现已准入的下单接口 | 保持独立后续能力，不从研究或管理建议自动触发。 |

Gateway 的单账户 holdings/assets 信封与 `analytics.build` 使用的 `accountResults` 列表不同，薄 wrapper 应显式映射，保留账户身份和 provenance。新响应不自动证明价格新鲜、全账户覆盖或历史 PIT 可用，时间与范围必须分别检查。

## 真实数据留在本地

`niulai/holdings/test_analytics.py` 中有可复用的合成用例。`test_snapshot_strict.py` 和 `test_position_totals.py` 会读取历史持仓、资产、分类或收益文件，不能直接作为 LangSmith dataset 上传。

重新构造完整空仓、读取失败、部分类型覆盖、账户歧义、重复合约、账户／币种不匹配、金额缺失、价格时间未知，以及陈旧或 unresolved 回执等用例。云端只记录允许共享的合成数据、状态、时间和配置版本，真实持仓、账户标识与私有路径保留在本地。

`shared/market_data_mcp/adapters/tiger.mjs:83` 将读取标为 `idempotentHint:false`。经济意义上的只读仍可能更新凭证状态。Graph 恢复应读取已提交的回执，并服从 `shared/tiger/bridge.py` 的 lease/checkpoint fence，不能盲目重放。

## 在总架构中与研究并列

Trading Agent 下的投资研究与持仓／组合分别提供入口。研究可消费明确范围的只读快照，组合复核可消费研究结论。两边都保留独立状态和验收，再按后续确定的 pipeline 配置组合。完整迁移顺序见[迁移方案](../plans/langchain-agent-migration.md)。
