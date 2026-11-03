# Resource Manager

自有设备的跨项目资源仲裁与受管命令入口，独立Git仓库。
初始`manager.py`、`migration.py`与仲裁表来自Visual Memory的`142cf66b6`实现；
本仓库继续独立维护，应用不再复制资源管理器源码。

## 构建与调用

```bash
python3.12 -m venv .venv
.venv/bin/pip install 'psycopg[binary]==3.3.4'
# 源码先commit；build会拒绝未提交源码。
.venv/bin/python build.py --install
~/.local/bin/resource-manager version
~/.local/bin/resource-manager paths --device local
~/.local/bin/resource-manager install-db
~/.local/bin/resource-manager run < request.json
~/.local/bin/resource-manager reconcile <request_id>
```

runtime是`dist/<commit>/resource-manager.pyz`中的已编译字节码；bin只链接该产物。
需要同事务仲裁的Python应用可把该固定runtime路径安装到自己的Python搜索路径，
导入`owned_compute.manager`，不依赖本仓库源码目录或Visual Memory包。
CPU命令入口不接受未准入GPU模型；GPU driver仍须提供实际成功准入及原主机租约。

## 路径及数据

| 设备标识 | workspace | 模型 | 数据 |
|---|---|---|---|
| local／office／wsl | `~/work/projects` | `~/work/models` | `~/work/data` |
| single5090／dual5090 | `~/sry/projects` | `~/models` | `~/sry/data` |

项目代码与版本构建在workspace的项目内，任务临时work在数据目录的`<project>/work/<task>`。
临时work不是产品存储；应用须把唯一结果保存到PG或正式项目数据位置。
协调器收到退出结果并提交PG后，才删除临时work；运行未知先核对原unit，不能删或异机重推。
来源／结果／实际owner和恢复状态共用既有PostgreSQL，不每项目建新数据库。

`run`请求包含`project`、`task`、`priority`、带时区绝对`deadline`、`script`、`args`、
`asset_paths`及已准入`candidates`。candidate的binding包含实际`host`、`placement`、
项目`code`、固定应用`python`、固定`resource_runtime`、CPU／内存边界及原资源租约。
成功请求复用PG结果，不为验收重复模型工作。无GPU模型推理的安装验线脚本为
`examples/verify_workspace.py`。

旧生产binding和仍在途请求不热改；目录迁移先登记owner／消费者，再切换、读回和退役。
WSL已获用户2026-11-03恢复通知。补齐冻结runtime用
`.venv/bin/python deploy.py --host wsl --revision <commit>`；只补目标主机，
不因部署工具更新而改变应用runtime pin或重复其他主机的成功任务。
