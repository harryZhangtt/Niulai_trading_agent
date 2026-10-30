# 牛来统一价格与持仓日报

复用唯一任务 `6ad3d456669c8191978ec6200339efbb`，纽约交易日13:00/19:00。
不新增调度器或研究数据库；只复用独立的私密凭据存储，不启用研究任务或修改提醒线。

## 单次命令

安装 requirements.txt（官方Tiger SDK、XNYS日历、pandas==2.2.3及PDF渲染）。pandas3.x与旧价格引擎日期比较不兼容，本次实测2.2.3恢复周末门禁；使用独立虚拟环境，不改变共享依赖。
生产入口必须先从唯一私密存储恢复授权，不能依赖运行容器保留目录。详见文末v4契约。原 daily_compact_pipeline.py 仅作为内部执行器；生产默认拒绝未经验证的本地凭据。

```
python private_profile.py --mode run --out RUN_DIRECTORY
```

服务访问凭据仅通过隐藏TTY stdin传入，禁止放在命令、日志、文件、ZIP或邮件中。

采集一次，只读账户、成交、公司行动、转仓及收盘报价；复用现有计算函数生成 daily.json，HTML和一页PDF共享该规范数据。每阶段最长240秒，失败保留source checkpoint/status，不把旧文件当新成功。`--offline`仅重算本目录冻结sources.json，明确记录offline_frozen。

13:00价格模块仍检查当日盘中价；持仓日报显示最新持仓快照和最近已完成交易日的收盘盈亏，并标明不同日期。19:00使用当天已完成交易日。没有可靠的当日逐股字段时，不冒充盘中P&L。周末手动测试回退最近已完成XNYS交易日。

## 单一工作流执行顺序

1. 恢复最新workflow.json、alerts.json、alerts.sqlite、research.sqlite，保留实际版本；验证启用角色和唯一automation_id。先由price_watch真实时钟/交易日/槽位/去重门禁判定。非到期或已发布槽位不重复发送。
2. 到期后运行既有价格引擎和本日报命令，分别限时、保留错误；Tiger失败不能阻止有效价格提醒，价格失败不能抹掉有效持仓日报。默认仅STANDARD账户；不混PAPER或币种，不交易。
3. 总持仓市值=同账户/币种券商返回marketValue合计，不含现金。与历史收盘可估值小计、账户NAV、内嵌杠杆敞口区分。金额缺失则总额未知。逐股税费前P&L按金额降序（缺失最后）、显示百分比、行业条形图与资金/行业构成；不补造费用、股息或现金。
4. 保存HTML、PDF、sources/result/status，相关DB使用最新版本guard保存并独立回读。若行情或持仓不完整，输出明确partial和缺口。
5. 同一个任务通过原生会话输出，并用已授权Gmail发到 `you@example.invalid`。每次先get_profile核对该账户；不得猜地址或改用其他发件人。主题：`【DAILY HOLDING UPDATE｜每日持仓】YYYY-MM-DD · HH:MM NY · 日盈亏 AMOUNT`，测试加`【TEST】`。主题无HTML/Markdown；正文首行加粗放大。正文包含总持仓、日期/快照时点、日盈亏金额/%/口径、覆盖缺口、全部命中规则和新增规则，附完整日报链接（或受支持的附件）。不省略启用规则名单。
6. 复用research.sqlite/job_runs和niulai_state.py record-run，邮件去重键 `portfolio-email:{automation_id}:{NY_date}:{slot}:{recipient}`。槽位不因config revision更新而重新发送。发信前保存准备记录；成功后保存独立sent记录及真实Gmail message ID。网络结果不明时标unknown，查Sent确认后再决定，禁止盲目重发。原生发布、Gmail接受、手机推送收悉分别记录；不声称设备已收到。

## 恢复和限制

包只含脚本/模板/测试和非凭证样本。运行环境须挂载现有私密profile，新的隔离环境无法访问时报告auth/profile_missing；不能从ZIP恢复令牌，不能依赖Price Alert Studio。配置更新不会保证未来运行环境保留授权。
直接逐股券商日P&L仍不可用；目前通过完整成交反推历史数量，使用相邻收盘复算。未知公司行动、转仓、币种/合约冲突阻塞相关计算；不可用源不解释为空仓。
测试通过不等于未来数据完整或通知已送达。旧日报和已发布槽位保留，不回写伪造新鲜时间戳。

## 用户追加的交付要求
总资产净值（含现金）、证券持仓市值、现金余额同时列出。净资产取同账户同币种券商netLiquidation，现金取cash，差额保留为其他净资产/时点残差；禁止用buyingPower代替。
邮件正文保持完整的总览、全量逐股金额/百分比、行情规则清单、来源时点和缺口，不因附件而删减。每封邮件必须以multipart/mixed直接附application/pdf，完整嵌入字体的一页PDF为实际字节附件；不是ChatGPT链接，也不是附件名占位。附件失败需明确报告，不虚称已附。原频率、账户和去重保持不变。

统一邮件生成器：compose_digest.py --portfolio RUN/daily.json --price-message RUN/price_message.txt --pdf RUN/daily.pdf --subject SUBJECT --recipient you@example.invalid --output RUN/email_payload.json。先准备两个分支的最终正文，再调用一次发送；价格分支失败时price_message必须包含确切失败，不能静默留空。一次payload含完整价格正文、完整逐股P&L表、总资产/现金/持仓和真实PDF字节。发信只由原调度任务调用Gmail一次；生成器不联网也不发信。历史测试加--historical。

## 价格视觉分组 v2
单一只读适配器 price_summary_view.py 读取已保存的当前评估和紧邻的上一次真实采样；不产生新行情、信号、提醒或发送记录。生产调用必须 --run-id EXACT_CURRENT_RUN_ID，不能默认选择旧报告；若本次行情失败，合并邮件必须展示实际失败，不能悄悄借用旧报告。手动格式测试才允许明确历史重绘。

价格模块完成保存后，运行：
python price_summary_view.py --db RECOVERED/alerts.sqlite --rules RECOVERED/alerts.json --run-id EXACT_CURRENT_RUN_ID --out RUN/price_view
python render_price_pdf.py RUN/price_view/price_view.json RUN/price_details.pdf
python compose_digest.py --portfolio RUN/daily.json --price-message RUN/price_message.txt --price-view RUN/price_view/price_view.json --price-pdf RUN/price_details.pdf --pdf RUN/daily.pdf --subject SUBJECT --recipient you@example.invalid --output RUN/email_payload.json

完整分组：蓝色=两次有效报价从未满足到满足；绿色=两次采样均满足（不证明期间持续）；青色=缺口补齐或首次确认；琥珀=缓冲接近/触及后退出；红色=未到价；灰色=无法判断。额外单列实际new_signals记录与方向性证据，不能等同于新穿越。修改提醒线、相同报价时点、前次来源失败或回放不能证明新市场事件。每条规则原始线、缓冲边界、上次和本次报价、差距%、时点及未核验附加条件保留；所有规则+错误必须等于冻结启用范围。quote-only单列，不冒充启用提醒。
同一份规范JSON驱动邮件彩色表格、全规则HTML和价格PDF；原持仓PDF仍为一页。合并邮件现在附持仓PDF＋价格明细PDF两份实际附件，完整正文不删减，只发一次。scope/hash/session不一致则拒绝该价格视图，报告失败但继续独立的有效持仓结果。

## 2026-10-27 授权与冷启动修复（v3）

本次已确认的失败发生在本地启动：NIULAI_PROFILE_DIR 未设置且既有私密目录未挂载；未调用 Tiger 业务接口。恢复脚本 ZIP 不会恢复授权。不得把目录存在、一次登录成功或本地测试通过当作跨次执行的持久部署证明。

- 安装时使用隔离环境并加 `--no-cache-dir`；恢复依赖后先运行 `daily_compact_pipeline.py --preflight --profile PRIVATE_PROFILE --out CHECK_DIRECTORY`。预检在独立进程内检查只读授权/刷新能力，不联网授权、不打印令牌、不创建缺失凭据目录。原生依赖崩溃记录 dependency_process_crash；最多进行一次相同锁定版本的无缓存重装，不循环降级或重试。
- 真实执行仍是一条原命令；它自动进行预检。显式 --profile 配错时失败，不偷偷切换到另一个账户目录。未传参数时才采用已存在的固定回退目录。只读 scope 扩张仍被拒绝。
- 首次登录后的 account-refs.json 由真实账户列表初始化，稳定保留随机引用；只有一个实际 STANDARD 账户时才继续，不任选多个账户中的第一个。
- 行情权限或完整历史 P&L 证据缺失时，保留已核验的当前持仓/资产，日盈亏保持未知。不得用累计盈亏、旧日报或零值填补。
- 邮件/原生标题必须显示持仓失败或部分完成；缺失名单的期望数未知，不能写成空仓、0/0 已完成或系统已修复。成功价格分支仍与持仓状态一起发送一封完整摘要。
- 活跃 OAuth 缓存只能由一个执行 owner 使用，存于受保护且被实际挂载的持久目录；不在 Library、ZIP、Git 或邮件保存凭据。不从其他旧系统复制令牌。凭据目录0700，文件0600；保留现有文件锁和官方刷新机制。
- 跨次持久性验收：在下一次独立执行环境中观察同一私密挂载，再完成真实账户/持仓/资产读取；此证据缺失时 persistence_verified 必须保持 false/unknown。仅改 workflow.json 或授权一次不能消除这一外部依赖。
- Tiger 官方说明 OAuth 每次授权最多15天；到期/撤销必须重新授权。不得承诺永不过期或一定准点送达。来源：https://docs-en.itigerup.com/docs/authentication。

手动更正使用独立 correction request_id 并关联原 Gmail message ID；保留原生产槽位去重及原报告，不重新生成既有市场事件。


## 2026-10-27 私密凭据持久存储 v4（优先于v3私密挂载要求）

v3未验证的容器持久挂载不再是生产凭据来源。唯一后端为独立 owner-private encrypted store：project_id `REPLACE_PRIVATE_STORE_PROJECT_ID`，origin `https://private-credential-store.example.invalid`。不依赖任何旧价格应用。AES-256-GCM密文保存在服务私有R2；密钥只在平台secret环境变量，凭据不进入Library/Git/报告。

每次既有任务运行先使用 Sites get_site 对该精确project_id回读：owner、custom、仅you@example.invalid一个owner、无其他用户/编辑/组/外部访问者、来源URL完全匹配。取本次原生短时 siwc_bypass_bearer_token，只在工具内存中传递。启动上面的命令后，通过隐藏TTY stdin输入JSON `origin` 和 `bearer`；不把真实值写入任务提示或环境配置。

桥接器获得有界独占租约，从密文恢复全新0700临时目录及0600文件。现有SDK负责只读授权及刷新；每次SDK持久化新令牌后立即向私密存储条件写回。运行结束确认提交再释放租约/清理临时目录。并发领取冲突409不能自行覆盖；等待下次既有执行，不创建任务或要求重新授权。生产内部入口还验证实际远端租约及恢复文件内容，伪造环境标记不能绕过；`--local-bootstrap`仅显式手动连接/测试。

私密存储访问/网络/缺少临时目录不等于Tiger授权过期。先恢复同一份私密存储；服务访问凭据过期则重新通过Sites获取本次访问，不要求用户重新Tiger授权。仅官方确认grant过期/撤销、refresh拒绝等真正授权错误才提示同意授权，禁止自动打开授权或反复索取凭据。仍须尊重Tiger官方每次grant最多15天；短access token到期由SDK刷新，不是每小时重新登录。

实际验证：移走原本地目录→空目录恢复→真实48项持仓和资产读取→强制测试轮换access/refresh→条件保存→第二个独立进程再次空目录恢复并成功运行完整采集。revision6/8提交确认，未提示重新授权。这证明已测试的冷恢复和跨进程轮换；不等于下一次真实定时执行已经通过。`next_scheduled_run_readback_verified=false` 保留到实际定时运行成功，届时保存实际证据，不能自填true。

服务访问失败、租约冲突、写回失败与Tiger失败分别记录。保持完整价格/持仓单封邮件、两份PDF、原去重与原频率；部分阶段失败仍输出确切缺口，不回退旧数据冒充当前成功。服务没有新增调度、MCP或访客仪表盘。
