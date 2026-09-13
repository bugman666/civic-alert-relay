# Civic Alert Relay

聚合权威开放数据源里的地质与气象灾害信息（地震、海啸、极端天气等），再通过 WebPush、Telegram Bot、Webhook 等渠道尽快推给订阅方。

面向需要「早知道、少漏报」的公众、社区志愿者和小型公民倡议组织。可自托管，不设付费墙。

## 做什么

1. **接入开放源**：例如 USGS 地震 feed，以及其他可公开获取的灾害/预警数据
2. **规范化事件**：统一成内部事件模型，便于去重与订阅过滤
3. **多渠道分发**：WebPush、Telegram Bot、Webhook；订阅方可按区域/震级等条件筛选
4. **实时出口**：WebSocket 长连接，方便看板或下游服务跟事件流

## 当前状态

仓库已有可运行骨架：进程能起来，[`GET /healthz`](#如何运行) 返回正常。拉取、规范化、扇出和 WebSocket 还是占位模块，见 [#2](https://github.com/bugman666/civic-alert-relay/issues/2)、[#3](https://github.com/bugman666/civic-alert-relay/issues/3)、[#4](https://github.com/bugman666/civic-alert-relay/issues/4)。

- [x] 最小可运行骨架（配置、健康检查、进程入口）
- [ ] USGS（或同类）拉取与去重（[#2](https://github.com/bugman666/civic-alert-relay/issues/2)）
- [ ] Redis 扇出 + 至少一条出站通道（Webhook 或 Telegram）（[#3](https://github.com/bugman666/civic-alert-relay/issues/3)）
- [ ] WebSocket 事件流（[#4](https://github.com/bugman666/civic-alert-relay/issues/4)）
- [ ] PostgreSQL 订阅与历史

## 计划中的技术栈

| 层 | 选型 | 用途 |
|----|------|------|
| 服务 | Python (FastAPI) | 拉取、规范化、API |
| 队列 | Redis Pub/Sub | 低延迟扇出 |
| 实时 | WebSocket | 长连接推送 |
| 存储 | PostgreSQL | 订阅、事件历史、投递状态 |

长连接与高频轮询需要常驻进程；灾害通知走内存队列扇出，适合跑在一台可长期在线的机器上。Compose 会一并拉起 Redis 和 PostgreSQL，方便后续接线；骨架阶段进程还不连它们。

## 如何运行

依赖：Docker Compose **或** Python 3.11+。不需要商业托管账号。

### Docker Compose（推荐）

```bash
git clone https://github.com/bugman666/civic-alert-relay.git
cd civic-alert-relay
docker compose up --build -d
curl -sS http://127.0.0.1:8080/healthz
```

看到 `"status":"ok"` 即表示服务已起来。停止：

```bash
docker compose down
```

等价 Makefile 目标：`make compose-up` / `make compose-down`。

### 本地 Python

```bash
git clone https://github.com/bugman666/civic-alert-relay.git
cd civic-alert-relay
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make test          # 单元测试
make run           # 默认监听 :8080
# 或
make smoke         # 短时拉起进程，检查 /healthz
```

`make run` 之后：

```bash
curl -sS http://127.0.0.1:8080/healthz
```

示例：

```json
{
  "status": "ok",
  "service": "civic-alert-relay",
  "version": "0.1.0",
  "ingest": "stub",
  "normalize": "stub",
  "fanout": "stub",
  "realtime": "stub"
}
```

`GET /` 返回服务名和健康检查路径。

常用环境变量（覆盖 `configs/config.example.env`；也可复制为仓库根目录的 `.env`）：

| 变量 | 含义 | 默认 |
|------|------|------|
| `CAR_HOST` | 监听地址 | `0.0.0.0` |
| `CAR_PORT` | 监听端口 | `8080` |
| `CAR_LOG_LEVEL` | 日志级别 | `info` |
| `CAR_REDIS_URL` | Redis（#3 才会真正连接） | `redis://127.0.0.1:6379/0` |
| `CAR_DATABASE_URL` | PostgreSQL（订阅/历史，尚未使用） | `postgresql://civic:civic@127.0.0.1:5432/civic_alert` |

## 仓库结构

```
civic_alert_relay/   FastAPI 进程：配置、/healthz、占位模块
  config.py          环境变量（CAR_*）
  ingest.py          拉取开放源          #2
  normalize.py       事件规范化与去重    #2
  fanout.py          Redis 扇出 + 出站   #3
  realtime.py        WebSocket 事件流    #4
configs/             示例环境变量
tests/               /healthz 与配置测试
scripts/smoke.sh     拉起进程并打 /healthz
Dockerfile
docker-compose.yml
```

## License

[MIT](LICENSE)
