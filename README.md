# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

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

锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`。

整坊鼓风配额：每坊一行（坊、剩余分钟、更新时刻，分钟为非负整数），种子剩余分钟为 **1**。登记一条峰值须在同一事务内原子扣减 1 分钟；剩余不足 1 分钟则中文挡下、峰值不得入库。改锅态不扣分钟，分钟不掺进已出胶门槛。顶栏挂「锅位作业台」与「鼓风台」：鼓风台专页展示配额、可按坊筛，操作工只读，管理员可把剩余分钟补回去。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
