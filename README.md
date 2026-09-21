# SmartMaaS Gateway

> MaaS 平台的智能路由与多级缓存引擎
> 中国电子杯第三届高校 ICT 产教融合创新大赛 · 赛题七（命题单位：中电金信软件有限公司）

一个可独立部署的大模型网关：接收 OpenAI 兼容请求，按后端实例的实时负载动态调度，
并用多级缓存 + Prefix 亲和降低首字延迟（TTFT）和运营成本。

---

## 当前状态：脚手架阶段

代码骨架、配置协议、部署脚本和 Mock 服务已经可用，**核心算法模块待三人分别实现**。

| 模块 | 状态 | 负责人 | 对应规划 |
|---|---|---|---|
| 配置 / 日志 / 请求上下文 | ✅ 可用 | A | §16、§8 P0-31 |
| 后端注册中心 | ✅ 可用 | A | §4 P0-07~09 |
| `/health`、`/admin/backends`、`/admin/stats` | ✅ 可用 | A | §14.2~14.4 |
| 轮询调度（RR 基线） | ✅ 可用 | B | §5 P0-12 |
| Mock 模型服务 | ✅ 可用 | C | §9 P0-35 |
| 指标采集（含 TTFT/TPOT） | ✅ 可用 | A | §8 P0-32 |
| **聊天转发 `/v1/chat/completions`** | ⛔ 待实现 | **A** | §3 P0-01/02/03 |
| **最小连接数 / 动态评分调度** | ⛔ 待实现 | **B** | §5 P0-13/14 |
| **L1 / Redis / 语义缓存** | ⛔ 待实现 | **B** | §7 P0-24/25 |
| **健康检查 / 超时 / 熔断** | ⛔ 待实现 | **A** | §4 P0-10、§6 |
| **Locust 压测与对照实验** | ⛔ 待实现 | **C** | §10 |

未实现的模块会抛 `NotImplementedError` 并在日志里说明，不会静默返回错误结果。
`app/main.py` 里有一段临时的容错（`_try_start`），让未实现的组件不阻断启动 ——
**等第 1 周的 P0 全部落地后要删掉**。

---

## 快速开始

### 方式一：Docker Compose（推荐，一键起全套）

```bash
cp .env.example .env          # 按需填 SMARTMAAS_ADMIN_TOKEN
cp config/config.example.yaml config/config.yaml
docker compose up --build
```

起了 5 个服务：

| 服务 | 地址 | 说明 |
|---|---|---|
| gateway | http://localhost:8000 | 网关本体 |
| redis | localhost:6379 | L2 缓存 |
| mock-fast | http://localhost:9001 | prefill 120ms，模拟空闲 GPU |
| mock-mid | http://localhost:9002 | prefill 700ms，模拟中等负载 |
| mock-slow | http://localhost:9003 | prefill 2500ms，且每 90 秒故障 25 秒 |

验证：

```bash
curl localhost:8000/health
curl localhost:8000/admin/backends
curl localhost:8000/admin/stats
```

### 方式二：本地裸跑

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 起三个 Mock 后端（各自一个终端）
python -m mock.mock_server --name mock-fast --port 9001 --prefill-ms 120  --per-token-ms 8
python -m mock.mock_server --name mock-mid  --port 9002 --prefill-ms 700  --per-token-ms 25
python -m mock.mock_server --name mock-slow --port 9003 --prefill-ms 2500 --per-token-ms 60

# 起网关
uvicorn app.main:app --reload
```

本地裸跑时要把 `config/config.yaml` 里的 `base_url` 从 `http://mock-fast:9001`
改成 `http://127.0.0.1:9001`（compose 用的是服务名，本机跑要用 localhost）。

### 提交前检查（§18）

```bash
ruff check .
pytest -q
```

---

## 目录结构

```text
smartmaas-gateway/
├── app/
│   ├── main.py              FastAPI 入口与 lifespan
│   ├── api/                 HTTP 接入层：chat / admin / health
│   ├── backend/             后端实例模型、注册中心、转发、健康检查
│   ├── router/              调度策略：round_robin / least_conn / dynamic
│   ├── cache/               多级缓存：base / memory / redis / semantic / prefix
│   ├── resilience/          限流与熔断
│   ├── metrics/             指标采集
│   └── core/                配置、日志、跨模块上下文
├── mock/mock_server.py      OpenAI 兼容的 Mock 后端（含故障注入）
├── benchmark/locustfile.py  压测脚本
├── tests/{unit,integration} 测试
├── config/config.example.yaml
├── docs/                    设计报告、性能报告、图表（§11）
└── scripts/                 一键启动、实验编排脚本
```

---

## 三人分工速查

**A（网关后端 / 集成）**：`app/api/`、`app/backend/proxy.py`、`app/backend/health_checker.py`、
`app/resilience/`、整体联调、设计报告总稿。

**B（调度 / 缓存算法）**：`app/router/least_conn.py`、`app/router/dynamic.py`、
`app/cache/` 全部、缓存 Key 规则、相关单元测试。

**C（GPU 部署 / 压测 / 观测）**：`mock/`、`benchmark/`、GPU 环境、对照实验、
性能图表、测试与性能分析报告。

分支协议（§13.1）：`main` 稳定版，`dev` 日常集成，功能走 `feature/a-*` / `feature/b-*` / `feature/c-*`。

---

## 环境说明

- 规划文档 §18 写的是 **Python 3.11**；本机实测 **3.12** 也可正常运行。
  请勿使用 3.13+，部分依赖 wheel 尚不完整。三人**必须统一版本**，
  否则 `requirements.txt` 装出来的东西不一样，压测数据会不可比。
- `config/config.yaml` 是本机实际配置，**已在 `.gitignore` 中**，不会入库；
  入库的只有 `config/config.example.yaml`。
- 所有密钥走环境变量，配置文件里只写变量名（§13.3、§18）。

---

## 常见问题

**Q：`config/config.yaml` 不存在会怎样？**
A：`load_settings()` 回退到内置默认值并打一条 warning，服务照常启动，
但后端列表是空的。所以本地开发请务必从 example 复制一份。

**Q：Redis 没起，网关会挂吗？**
A：不会。设计上所有缓存故障都降级为"未命中"（§7 P0-25、§22 创新点 C）。
`/health` 也会如实上报 redis 状态，但不会因此变成不健康。

**Q：怎么演示"某个节点突然变慢"？**
A：不用重启进程，直接改 Mock 的运行参数：

```bash
curl -X POST localhost:9003/mock/config \
     -H 'Content-Type: application/json' -d '{"prefill_ms": 30000}'
```

**Q：TTFT 和 TPOT 怎么测？**
A：必须用流式请求。`benchmark/locustfile.py` 已经在流式路径里埋点，
把两者作为独立事件上报，Locust 统计表里能直接读 P99。
这两个指标是决赛"效果验证"30 分的评分依据，从 Mock 阶段就要开始采集。
