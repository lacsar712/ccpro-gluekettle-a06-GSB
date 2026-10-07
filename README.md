# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后顶栏可在「锅位作业台」与「鼓风台」间切换：点锅登记煮胶峰值并改状态；鼓风台按坊展示整坊鼓风剩余分钟，管理员可补分钟。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

- **出胶门槛**：锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**（`backend/app/domain.py` 的 `assert_can_set_status`）。鼓风分钟不掺进此门槛。
- **鼓风配额**：每坊一行配额（坊、剩余分钟、更新时刻，剩余分钟为非负整数并有数据库 CHECK 兜底）。登记峰值时在**同一事务**内做条件扣减 `UPDATE … WHERE remaining_minutes >= 1`：不足 1 分钟返回中文错误且峰值不入库；两名工几乎同时抢交时靠行锁串行化，只有先到那条入库且剩余变 0。改锅态不扣分钟。
- **权限**：操作工对鼓风台只读；仅管理员可在鼓风台把剩余分钟补回去。

### API 摘要

| 方法/路径 | 说明 |
| --- | --- |
| `GET /api/workshops` | 坊列表 |
| `GET /api/board?workshop_id=` | 锅位作业台（含本坊 `remainingMinutes`） |
| `GET /api/quotas?workshop_id=` | 鼓风台配额行，可按坊筛 |
| `POST /api/quotas/{workshop_id}/topup` | 管理员补分钟（正整数） |
| `POST /api/kettles/{id}/cooks` | 登记峰值（同事务扣 1 分钟，不足则 400） |
| `POST /api/kettles/{id}/status` | 改锅态（不扣分钟，出胶照旧校验峰值） |

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
