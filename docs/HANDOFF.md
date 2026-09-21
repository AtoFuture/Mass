# 交接文档 · SmartMaaS Gateway

> **这份文档是给接手的 AI 编码 agent（Codex）看的。**
> 它描述项目当前真实状态、不可破坏的契约、和下一步该做什么。
>
> 维护规则：**只更新对应小节，不要重写全文**。每次交接在 §8 追加一条记录。
> 路径：`docs/HANDOFF.md`

---

## §0 · 额度交接提示词

### 先看这里：怎么触发

**Codex 大概率看不到自己的剩余额度。** 5 小时额度是账户级的限流状态，
不是模型能在对话里查到的信息 —— 它既没有工具去查，凭感觉猜出来的
"还剩 5%" 也不可信。所以**触发这件事，实际上得由你来做**：

1. **首选**：你自己盯着 Codex 界面上的额度显示（`/status` 能看到 5 小时
   窗口的剩余比例）。掉到 5% 左右时，把下面那段提示词发给它。
2. **省事**：懒得盯就每隔一两小时发一次。这个提示词是**幂等**的 ——
   任务做一半时发，它会如实记录进度然后停；没做一半时发，它就是一次
   常规的状态同步。多花不了几个 token。
3. **应急**：感觉快断了就直接发，不用等真的到 5%。

> ⚠️ 提示词里同时写了"如果你能自己查到额度就自己判断"的分支。
> 万一 Codex 哪天支持了，它会自己照做；不支持也不会瞎编一个百分比，
> 而是退回到"每完成一个任务单元就同步一次"。**两种情况下进度都不会丢。**

### 提示词（整段复制给 Codex）

```text
你正在为 SmartMaaS Gateway 项目写代码。请先读完 docs/HANDOFF.md 全文再动手。

以下是一条硬性要求，优先级高于所有功能任务：

【额度交接协议】
当你的 5 小时滚动额度剩余约 5% 时 —— 或者你判断当前会话剩余的产出能力
已不足以完成下一个完整任务单元时 —— 你必须立即停止写功能代码，
转为更新 docs/HANDOFF.md，然后结束会话。

不要为了"再改完这一点"而拖延。写到一半、没跑过测试的代码，
比没写的代码更糟：接手的人无法判断它是能用的还是半成品。

具体步骤：

1. 停手。不要开始任何新的功能改动。

2. 先跑验证，把真实结果记下来：
     .venv/bin/ruff check .
     .venv/bin/python -m pytest -q
   如果测试是红的，如实写进文档。不要隐瞒，不要临时注释掉失败的用例，
   不要为了让数字好看而删测试。

3. 更新 docs/HANDOFF.md 的这几节：
   - §2 当前状态 —— 改成本次结束时的真实状态（哪些从"待实现"变成了"可用"）
   - §4 待办清单 —— 删掉已完成的；把正在做但没做完的那一项保留在清单里，
     标注「进行中，未完成」，并写清楚：卡在哪一步、已经改了哪些文件、
     下一步具体该做什么。这一条最重要，写细一点。
   - §7 坑与决策记录 —— 追加本次新踩的坑、做过的取舍、发现的坑点
   - §8 更新记录 —— 追加一行：
     - YYYY-MM-DD HH:MM · <一句话说明本次完成了什么> · 额度交接

4. 提交，保证下一次会话从干净工作区开始：
     git add -A
     git commit -m "docs: 额度交接，更新 HANDOFF"

5. 最后用一小段话告诉用户三件事：
   - 这次做完了什么（对着 §4 的编号说）
   - 还有什么没做完，卡在哪
   - 下一次应该从哪一行、哪个文件开始

【如果你无法查询自己的剩余额度】
不要猜，也不要编造一个百分比。改为执行这两条：
  (a) 每完成 §4 里的一个完整任务单元（一个函数实现完 + 测试通过 + 提交），
      就顺手更新一次 §2、§4、§8；
  (b) 当用户说"额度快没了""准备交接"之类的话时，立刻执行上面的第 1~5 步。
无论哪种情况，§4 里「进行中，未完成」的标注都不能省 —— 那是最容易丢失的信息。
```

---

## §1 · 项目背景（30 秒看懂）

**中国电子杯第三届高校 ICT 产教融合创新大赛 · 赛题七**
命题单位：中电金信软件有限公司
题目：MaaS 平台的智能路由与多级缓存引擎设计

要做的东西：一个可独立部署的大模型网关。客户端把 OpenAI 兼容请求发给网关，
网关按后端各模型实例的**实时负载**（并发数、显存水位、历史延迟、错误率）动态选节点，
再用**多级缓存 + Prefix 亲和**降低首字延迟（TTFT）和成本。

- **初赛**（校内，2026-10-25 前）：考架构设计、核心调度算法、缓存策略、
  工程实现、Mock 仿真、理论分析。**不需要真实 GPU**，Mock 仿真报告是正式评分项。
- **决赛**（2026-12-03）：部署到真机集群，接 Qwen/DeepSeek 系列，
  按 **P99 TTFT 提升率** 和 **TPOT 提升率** 拿分（这一项 30 分）。

**团队 3 人**，本仓库的角色代号：

| 代号 | 角色 | 负责目录 |
|---|---|---|
| A | 网关后端 / 集成 | `app/api/`、`app/backend/proxy.py`、`health_checker.py`、`app/resilience/` |
| B | 智能调度 / 缓存算法 | `app/router/`、`app/cache/` |
| C | GPU 部署 / 压测 / 可观测 | `mock/`、`benchmark/` |

完整规划文档在仓库外：
`/Users/chi/ict/产教融合ict/中国电子杯_赛题7_参赛规划资料包/01_规划/规划文档.md`
本仓库所有代码注释里的 `§N` 引用都指向那份文档的章节号。

---

## §2 · 当前状态

**快照时间：2026-09-21 19:50** ｜ 代码快照提交：`9a1b34a` ｜ 分支：`main` + `dev`（内容相同）
（本节描述的是 `9a1b34a` 时的代码状态；文档本身的后续改动见 §8）

验证结果：`ruff check .` 全绿，`pytest -q` **60 passed**。

### 可用（已实现且被测试覆盖）

| 模块 | 文件 | 说明 |
|---|---|---|
| 配置加载 | `app/core/config.py` | YAML + 默认值回退，密钥只存环境变量名 |
| 日志与脱敏 | `app/core/logging.py` | §8 P0-31 字段集；`redact_headers()` 屏蔽 Authorization |
| 请求上下文 | `app/core/context.py` | `RequestContext` / `CacheContext`（见 §7 决策 1） |
| 后端实例模型 | `app/backend/model.py` | 滑动窗口延迟/错误率、prefix 亲和表（有容量上限） |
| 后端注册中心 | `app/backend/registry.py` | §4 P0-07~09，含动态增删与候选过滤 |
| 轮询调度 | `app/router/round_robin.py` | 平滑加权轮询（smooth WRR，nginx 同款） |
| 指标采集 | `app/metrics/collector.py` | 含 **TTFT / TPOT** 分位数，§8 P0-32 全字段 |
| Mock 服务 | `mock/mock_server.py` | OpenAI 兼容，故障注入 + 热更新 + TTFT/TPOT 时延建模 |
| HTTP 接口 | `app/api/health.py`、`admin.py` | `/health`、`/admin/backends` CRUD、`/admin/stats` |
| 部署 | `Dockerfile`、`docker-compose.yml` | 网关 + Redis + 三个不同速度的 Mock |

### 待实现（当前抛 `NotImplementedError`，每处都注明了负责人与规划条目）

`app/backend/proxy.py`、`app/backend/health_checker.py`、`app/api/chat.py`、
`app/resilience/limiter.py`、`app/resilience/circuit_breaker.py`、
`app/router/least_conn.py`、`app/router/dynamic.py`、
`app/cache/memory.py`、`app/cache/redis_cache.py`、`app/cache/semantic.py`

### 最关键的缺口

**端到端链路是断的**。`客户端 → 网关 → Mock 后端` 走不通，因为
`app/backend/proxy.py` 和 `app/api/chat.py` 还是接口桩。
这是 §4 待办里的第 1~4 项，也是 §20 v0.1 的主要验收标准。

---

## §3 · 不可破坏的契约

改这些会同时打断 B 和 C 的工作。**要改必须先说**（§13.4 要求公共接口变化必须在群里通知）。

1. **§15 模块间接口签名**
   - `Scheduler.select(request_ctx, backends) -> Backend` —— 只做选择，
     不发请求、不改 `Backend` 运行时状态、不假设候选非空（空则抛 `NoAvailableBackendError`）
   - `CacheLayer.get/set/invalidate` —— `get()` 未命中返回 `None`，**不抛异常**；
     任何一层故障都降级为未命中
   - `BackendRegistry.list_healthy(model)` / `add()` / `remove()`

2. **`config.yaml` 的键名**（§16）—— 三人共用同一份配置结构，
   加字段要给默认值，不要改已有键名。

3. **`POST /v1/chat/completions` 的请求/响应格式**（§14.1）——
   必须 OpenAI 兼容。§3 P0-01 的验收标准是"客户端只改 `base_url` 就能用"，
   所以 `ChatCompletionRequest` 开了 `extra="allow"`，**不要关掉**。

4. **在途计数的释放时机** —— `Backend.acquire()` / `release()` 必须成对，
   客户端断连、超时、流式中途异常都要走到 `release()`。漏一次，
   该实例的 `active_requests` 就永久偏高，最终被判定满载而 503。

---

## §4 · 待办清单（按推荐顺序）

> 顺序不是按负责人排的，是**按"解开阻塞的能力"排的**。
> 第 1~4 项打通端到端链路，做完之后 B 和 C 的模块才能被真正测起来。

### 第一优先：打通客户端 → 网关 → Mock（全部属于 A，但价值最高）

- [ ] **1. `app/backend/proxy.py` → `start()` / `close()`**
      建 `httpx.AsyncClient` 连接池并复用。每个请求新建 client 会重新做 TCP 握手，
      网关自身开销会掩盖优化收益，压测数据就不可信了。

- [ ] **2. `app/backend/proxy.py` → `forward()`（§3 P0-02 非流式）**
      返回 `(OpenAI 兼容响应体, 耗时毫秒)`。正确映射后端异常状态码。

- [ ] **3. `app/backend/proxy.py` → `forward_stream()`（§3 P0-03 SSE 流式）**
      透传 `data: {...}\n\n`，以 `data: [DONE]\n\n` 结束。
      **必须在这里埋 TTFT / TPOT 采集**，调用
      `metrics.record_request(ttft_ms=..., tpot_ms=...)`。
      TTFT = 发出请求到收到第一个 token；TPOT = 首 token 之后平均每 token 耗时。
      这两个数是决赛 30 分的评分依据，不能事后估算。

- [ ] **4. `app/api/chat.py` → 组装完整链路（§3 P0-01）**
      校验模型名 → 建 `RequestContext` → 算 `prefix_hash`
      → 查缓存（缓存未实现时直接穿透）→ `scheduler.select()`
      → `proxy.forward*()` → 写缓存 → 返回。
      错误码：非法模型 400、无可用后端 503、并发超限 429。

### 第二优先：稳定性与缓存骨架

- [ ] **5. `app/backend/health_checker.py`（§4 P0-10）** —— 周期探测，
      并发探测不要串行；任务要在应用关闭时取消并 await。
- [ ] **6. `app/resilience/limiter.py` → `ConcurrencyLimiter`（§6 P0-20）**
- [ ] **7. `app/cache/memory.py`（§7 P0-24 L1）** —— `OrderedDict` + `move_to_end()`
      就是现成 LRU，不用引 `cachetools`。TTL 惰性判断即可。
- [ ] **8. 缓存 Key 规范（§7 P0-28）** —— `cache_version + tenant_scope + model
      + system_prompt + conversation_history + user_message + 生成参数`，
      稳定序列化后取 SHA-256。**不得只用用户最后一句话当 Key。**

### 第三优先：算法与创新点

- [ ] **9. `app/router/least_conn.py`（§5 P0-13）**
- [ ] **10. `app/router/dynamic.py`（§5 P0-14）—— 本项目核心创新点 A**
      公式 `Score_i = αC_i + βL_i + γG_i + δE_i − ηH_i`，分数越低越优先。
      必须处理三个边界：冷启动 `avg_latency_ms` 为 None（**不能当 0**）、
      归一化基准取候选集 max、`gpu_memory_ratio` 缺失时整项按 0 处理。
- [ ] **11. `app/cache/redis_cache.py`（§7 P0-25）** —— Redis 挂了必须自动降级，
      只记 warning，不能让推理失败。
- [ ] **12. `app/resilience/circuit_breaker.py`（§6 P1-21）** ——
      `CLOSED → OPEN → HALF_OPEN → CLOSED`。**它的测试比实现更重要**：
      初赛"仿真测试方案"10 分要验证的就是熔断/慢节点剔除是否生效。
- [ ] **13. `benchmark/locustfile.py` 实跑（C，§10）** —— 五组对照实验。

### 收尾（等 P0 全绿再做）

- [ ] **14. 删掉 `app/main.py` 里的 `_try_start` / `_try_stop` 容错**
      （模块 docstring 里已标注"P0 完成后请删除"），改回直接 `await`。
- [ ] **15. `DELETE /admin/backends/{id}` 改成优雅下线** —— 现在是硬移除，
      应先置 `DRAINING` 等在途请求跑完。
- [ ] **16. `config/config.yaml` 补 `least_conn` / `dynamic` 的实测权重**，
      并做权重敏感性分析（§5 明确要求：不得把拍脑袋的权重描述成"最优"）。

---

## §5 · 工作规范

**编码**（§18）：Python 3.11+ 语法；4 空格缩进；`snake_case` / `PascalCase` / `UPPER_CASE`；
公共函数写类型注解；核心算法写 docstring 说明**为什么这么做**，而不只是做了什么。

**提交前必须跑**：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
```

**Commit 格式**（§13.2，一次提交只做一类事）：
`feat:` / `fix:` / `perf:` / `refactor:` / `test:` / `docs:` / `chore:`

**分支**（§13.1）：`main` 稳定版禁止直接改，`dev` 日常集成，
功能走 `feature/a-*` / `feature/b-*` / `feature/c-*`。

**Definition of Done**（§27）—— 一个功能同时满足才算完成：
有代码 · 有可复现的运行方式 · 至少 1 个正常测试 · 至少 1 个异常/边界测试 ·
README 或注释说明用法 · 配置项有默认值 · 不含密钥 · 合入后不破坏已有功能。

**禁止**：明文 Token / API Key 进配置或代码；把 `config/config.yaml`
（本机实际配置）提交入库；关掉或删除失败测试来让 CI 变绿。

---

## §6 · 验证方式

```bash
cd /Users/chi/ict/产教融合ict/smartmaas-gateway
.venv/bin/ruff check . && .venv/bin/python -m pytest -q
```

**本地起服务**（三个 Mock + 网关，各自一个终端）：

```bash
python -m mock.mock_server --name mock-fast --port 9001 --prefill-ms 120  --per-token-ms 8
python -m mock.mock_server --name mock-mid  --port 9002 --prefill-ms 700  --per-token-ms 25
python -m mock.mock_server --name mock-slow --port 9003 --prefill-ms 2500 --per-token-ms 60
uvicorn app.main:app --port 8001        # 注意 8000 被本机其他进程占用了
```

**注意**：`config/config.yaml`（本机配置，已 gitignore）里的 `base_url` 指向
`127.0.0.1:9001/9002`；跑 docker compose 时用的是服务名，两者不同。

**验证端点**：

```bash
curl localhost:8001/health
curl localhost:8001/admin/backends
curl localhost:8001/admin/stats
```

**演示"节点突然变慢"**（不用重启，压测/答辩演示用）：

```bash
curl -X POST localhost:9003/mock/config -H 'Content-Type: application/json' \
     -d '{"prefill_ms": 30000}'
```

---

## §7 · 坑与决策记录

> 这一节是本次交接最有价值的部分。接手时**先读这里**，能省掉重复踩坑。

### 决策 1：新增了 `app/core/context.py`（偏离 §17 目录协议，待团队确认）

§17 的目录树里没有这个文件。`RequestContext` / `CacheContext` 的字段
（`request_id`、`prefix_hash`、`tenant_scope`）被接入层、调度器、缓存、日志
四条链路共用，放进任何单一模块都会让另外三个反向依赖它。
替代方案是塞进 `backend/model.py`，代价是 `cache/` 要 import `backend/`。
**如果团队不接受这个偏离，改回去时要同步改 4 个文件的 import。**

### 坑 2：`_try_stop` 吞异常，掩盖了方法名写错

`app/main.py` 里关闭组件时调 `component.stop()`，但 `Proxy` 和 `RedisCache`
的关闭方法叫 `close()`，导致关闭阶段抛 `AttributeError`。
**测试全绿却没发现**，因为 `_try_stop` 本来就该吞掉关闭异常。
已修（显式传方法名），并补了回归测试
`test_lifespan_shuts_down_without_errors` —— 它断言"启动/关闭全程日志里不能有 ERROR"。
**教训：被 catch 吞掉的异常，只能靠断言日志级别来测。**

### 坑 3：平滑加权轮询的实际序列反直觉

`[A(w=3), B(w=1)]` 下 smooth WRR 给出的是 `A,A,B,A`，不是 `A,B,A,A`。
我一开始按后者写了测试断言，跑出来才知道错了。
它真正保证的性质是：**任意连续 Σweight 次窗口内，每个实例被选中的次数恰好等于其权重**
（即不存在被饿死的窗口）。测试现在断言的是这个性质。

### 坑 4：Mock 的 `max_tokens` 是双重上限

`mock_server` 里输出长度取 `min(请求的 max_tokens, 实例自身配置的 max_tokens)`。
写测试时如果只改请求侧、忘了改实例配置，实际输出会比预期短。

### 环境事实

- §18 写的是 Python **3.11**，但本机没有 3.11；实际用 **3.12.13** 建 venv，
  全部测试通过。**三人必须统一版本**，否则依赖装出来不一样、压测数据不可比。
- 本机 **8000 端口被另一个进程占用**（不属于本项目），所以示例里用 8001。
- 远端仓库 `https://github.com/AtoFuture/Mass` 目前**是空的、public 的，
  且尚未配置 remote**。仓库名 `Mass` 与项目名 `SmartMaaS Gateway` 不一致。
  每校每赛道只有 1 个晋级名额，public 仓库等于把方案提前公开 —— 建议转 private。

---

## §8 · 更新记录

> 每次交接追加一行，**不要删旧行**。

- 2026-09-21 19:50 · 初始化脚手架：55 文件、60 测试全绿、ruff 全绿，
  端到端链路待打通 · 人工交接（本次由 Claude Code 建立）
