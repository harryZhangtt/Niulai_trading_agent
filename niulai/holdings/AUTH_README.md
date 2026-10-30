# 牛来独立 Tiger 只读脚本

只有一个业务脚本：`niulai_tiger.py`。直接使用官方 `tigeropen==3.8.0`，不依赖网站、插件网关、数据库或定时服务。支持 Linux、macOS 与 POSIX 云环境；Windows 可用 WSL。

安装一次：

```bash
python -m pip install -r requirements.txt
```

把 `NIULAI_PROFILE_DIR` 指向可写、持久、私密的凭据目录。终端和云作业使用同一个实际挂载目录；不要把活跃刷新缓存复制成两个同时运行的副本。凭据目录和缓存分别限制为 0700、0600；文件锁避免共享目录内两个脚本进程同时刷新。共享挂载须支持文件锁。ChatGPT 的 `/tmp`、scratch 都不承诺持久，不能当作已经完成持久部署。

首次授权（本地终端）：

```bash
python niulai_tiger.py --profile "$NIULAI_PROFILE_DIR" login
```

云端或 SSH 环境使用设备授权：

```bash
python niulai_tiger.py --profile "$NIULAI_PROFILE_DIR" login --device
```

在 Tiger 官方页面核对应用名 **Niulai Read Only Holdings**、目标账户和只读权限。脚本固定只请求 `api.basic:read`、`api.account:read`、`api.trade:read`，不请求交易写权限；授权和刷新得到的更广权限会被拒绝写入缓存。不要把账户密码、令牌或授权码粘贴进聊天、命令参数或代码。

已完成授权后，只需下面两条命令：

```bash
python niulai_tiger.py --profile "$NIULAI_PROFILE_DIR" status
python niulai_tiger.py --profile "$NIULAI_PROFILE_DIR" fetch --all-accounts --out holdings.json
```

`status` 只查看本地 SDK 授权状态，不联网、不刷新。`fetch --all-accounts` 从官方账户接口取得本授权允许访问的全部账户，逐个、逐类读取 STK、OPT、FUT，市场与币种均为 ALL。此网关真实返回过 1010：`sec_type unsupported value: ALL`，脚本不再发送该证券类型。`--all-accounts` 指全部获授权账户，不代表所有资产类型。每个账户独立分组，并使用保存在私密目录的稳定随机 `accountRef`。不打印账户号，不合并跨账户持仓或合计金额。源接口实际提供的账户类型、状态、能力标签原样保留，不自行推测实盘/模拟盘。

可用 `--security-types STK` 明确只查股票，或 `--security-types STK OPT FUT FUND` 请求附加基金类别。输出在 `typeReads` 和 `coverage` 中逐项记录实际请求、成功和失败类型；未请求类型并不算已覆盖。

任一账户或类型失败时，文件明确写为 `partial` 或 `failed`，已有成功类型的持仓行仍保留；失败类型数量保持未知，绝不算作空仓。某账户全部请求类型均失败时，该组才是 `positions:null`。进程返回 2 表示部分或全部失败，0 表示本次指定的请求均成功；这仍不证明全资产覆盖。省略 `--all-accounts` 时，保持单账户固定校验；遇到多个账户停止，不猜测。

输出 `holdings.json` 时，另有 `holdings.last_successful.json` 原子保留最近一次指定范围全部成功的结果。随后读取部分失败或失败时，历史成功文件及其原始查询时间保持不变，最新文件明确记录新错误，绝不把历史持仓补成今天的新鲜结果。保存历史副本失败时停止覆盖原结果。

CLI 最多并行处理两个账户，每个账户使用独立只读客户端，同一账户内按类型依次查询。共用官方 SDK 会话的刷新单飞机制和外层进程文件锁。运行时仅输出已完成/总账户数与状态进度，不打印账号、随机标识或令牌。

输出只保留指定字段，原 JSON 数字用 `Decimal` 解析并输出为十进制字符串。优先使用服务明确返回的 `positionQty`；原始 `position/positionScale` 单独保留，不把可能缩放的整数强当真实股数。未提供的金额、市场、数量等为 `null`；零、负数和未知值不同。保留名称、合约 identifier、类型、币种、到期日、行权价、方向和乘数，不猜测 P&L、乘数或组合权重。`reportedUpdateTimestamp` 原样保留且不解释其时间单位或含义，不能当作已核验的行情时间。

`freshSourceResponse:true` 表示本次刚向 Tiger 查询成功，不证明每个价格实时。服务未明确提供的源快照/价格时间、现金余额、NAV 保持未知；不承诺全资产完整性。SDK 未收到 `scope` 或 `expires_in` 时可能采用请求范围或默认一小时期限，状态输出已标明这是 SDK 状态，不声称取得了完整原始授权回执。

已有 `HTTPS_PROXY`/`https_proxy` 会用于 OAuth 与业务请求，两者均启用 `CERT_REQUIRED`，连接/读取超时为 20/30 秒，不自动做网络重试。SDK 自身对近到期令牌刷新及一次 401 刷新重试保留官方行为，且处于同一文件锁内。脚本在 SDK 实际请求准备入口限制为账户、持仓及本版新增的资产/Prime资产/历史分析读取，其他业务接口（含交易写入）拒绝执行。

离线验证：

```bash
python -m unittest -v test_niulai_tiger.py
```

最初 16 项测试的基线记录单独保留；目前 24 项离线测试涵盖官方 SDK 的账户→持仓完整调用链（模拟传输）、只读范围、权限扩张拒绝、TLS/代理、文件锁与权限、原始十进制精度、缩放数量、多账户/类型部分失败、安全诊断、真实 ALL 拒绝原因对应的合成回归 fixture、源名称/合约/时间字段、成功历史保护，以及双客户端并发隔离/安全进度。测试不使用真实账户、令牌或在线接口；真实新授权和真实持仓读取的证据另行记录。

2026-10-27 冷启动验收补充：
`daily_compact_pipeline.py --preflight --profile PRIVATE_PROFILE --out CHECK_DIRECTORY` 是本地无网络预检；真实 fetch 才能验证服务器授权。新的环境只恢复代码、不带凭据时必然需要挂载同一现有私密 profile。不得把 scratch 或 /root 下普通目录宣称为平台已保证持久的密钥挂载。OAuth 每次授权最多15天，官方到期需要重新授权；不切换到权限更广的 RSA 认证来绕过。见 https://docs-en.itigerup.com/docs/authentication。
