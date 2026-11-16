# 凭证就绪状态：原提交仍需恢复核对

2026-11-16：保留现有远端凭证 owner。新的只读诊断已执行，但不能解除原
checkpoint 恢复锁，真实持仓迁移仍被挡住。新统一 `trading_agent` 尚未实现，
2027 没有启动；已有 2024/2025 实例保持原状。

| 输入 / 场景 | 执行的动作 | 实际结果 | 恢复处理 |
| --- | --- | --- | --- |
| Tiger snapshot smoke | 检查新鲜宿主授权和现有恢复锁 | `TIGER_PRIOR_OUTCOME_REQUIRES_RECONCILIATION`；新租约 0、券商读取 0 | 保留原 fence 和工作 profile |
| 第一项 owner 诊断 | 检查取回的源码文件权限 | Git 源码文件为 0644，本地检查拒绝；HTTP 0 | 保存失败记录；将同 hash 代码复制为新 0600 副本 |
| 远端健康查询 | 新鲜宿主授权，GET `/health` 一次 | 已初始化；当前租约不忙；revision 104 | 不能据此宣布 broker 授权或历史提交有效 |
| 原提交回执查询 | POST `/lease/checkpoint` 一次，仅携带原 commit/lease ID | 409，最近提交不匹配原提交 | 原提交保持 UNCONFIRMED，不重试、不解除 fence |

两项实际远端请求合计 HTTP 2、重试 0、券商读取 0、凭证写入 0。原 fence
前后 hash 一致。远端最近写回时间为 `2026-11-10T18:31:45.229Z`，这个时间不
代表当前 token 有效，也不能证明原故障的 checkpoint 从未成功。

## 测试怎样区分错误实现

| 验证层 | 结果 | 测试要挡住的问题 |
| --- | --- | --- |
| Tiger 组件 | 52 项通过 | 保留原 owner、请求准入、部分读取、锁与未知结果处理；含新增诊断客户端 14 项 |
| 独立客户端 | 27 项通过，0 跳过 | 错误 owner/来源在 HTTP 前拒绝；请求只能是两条诊断路由；超时不重试；凭证字段不输出；原 fence 不变 |
| 独立 Worker | 26 项，24 通过、2 失败，0 跳过 | 原 Worker 只按 commit ID 回 acknowledgement，错误/缺失 lease ID 也可能收到 200；两项失败原样保留 |
| 故意破坏规则 | Worker 4 项、客户端 8 项均被测试发现 | 写入、越过准入、扩大输出或错误恢复等破坏不能悄悄通过 |
| 实际 owner 诊断 | 请求按封存边界完成，原提交未核实 | 409 保持未知；没有把健康状态或过期租约变成重读许可 |

Worker 的只读路径检查通过：正常 health/minimal-checkpoint 用例没有尝试
`BUCKET.put`，状态也没有变化。旧 acquire 请求在租约过期后会创建新租约，
因此没有把它用于远端诊断。独立客户端报告中的 8 项破坏控制已包含在 27 项
执行总数中，不重复加到总数。

源代码和独立证据见 [reconciliation/](reconciliation/)。生成的证明、临时
数据和缓存留在忽略的 `.runtime/` 中。真实诊断的标量回执留在私密 smoke
目录，不包含凭证或持仓数据；原 native context、profile、policy 和 Git
访问凭证没有进入报告或快照。

## 现在能宣布什么

只读诊断路径可用；远端存储已初始化；原提交缺少可验证历史；恢复锁保留。
现有测试不能证明 Tiger 当前 grant 有效、无人值守运行稳定或新持仓子图已
完成。未来 scheduled business/email 验收仍未执行。

原 owner 需要核对现存权威凭证状态与原故障，或提供有效历史证据。新的
提交 journal 可以防止未来丢失回执，不能补出这次缺失的过去历史。完成恢复
核对后，才能合法执行新的 snapshot，逐项验收准入和分析，再提供新的测试 URL。

完整凭证安排与其余能力迁移清单见
[凭证存储与运行时访问](../../docs/architecture/trading-agent-credential-custody.md)。
