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
每节点一个跨项目资源账本；项目不各自建队列。旧部署仍使用Ubuntu既有PG，
节点本地模式使用本机Unix socket连接独立的`resource_manager`库，PG只保存资源状态，
不因此复制其他项目的业务数据。

## 节点本地运行与授予权切换

节点配置放`~/.config/resource-manager/node.json`，包含`node_id`、真实`host`、
物理`device`类别、Unix socket `dsn`及`schema`。`local`只是执行transport，
5090的物理路径类别仍为`single5090`，不会误用工作站的`~/work`目录。

先准备本地PG和配置，安装的是不可授予资源的pending账本：

```bash
resource-manager node-install --node-id single5090 --device single5090
resource-manager node-status
```

部署controller在旧PG原事务锁下执行`fence-host --host <真实主机名> --node-id single5090`。
它拒绝交接尚有reserved/running owner的设备，并在旧数据库安装授予权trigger，
因此旧pin的allocator也不能继续给目标设备分配新资源；其他设备和既有释放路径不变。
将返回的`fence_id`交给目标节点`node-activate --node-id single5090 --fence-id <id>`后，
本地allocator才可授予。中途失败不自动退回旧中心，不因超时清掉未知owner。

本地请求的candidate必须使用本机真实`host`和`placement=local`；`run`、
实际worker、退出证明和清理均使用本地argv，不经SSH。GPU应用仍须使用已准入模型driver，
不能用CPU通用命令入口绕过准入。节点库的trigger拒绝远端candidate和pending阶段授予，
同一节点的不同项目仍通过同一个PG事务仲裁。

本切片实现本机执行和旧中心授予权交接；节点之间的高层委托/接单协议尚未实现，
不将CLI安装或本地账本称作完整跨节点协商服务。

`run`请求包含`project`、`task`、`priority`、带时区绝对`deadline`、`script`、`args`、
`asset_paths`及已准入`candidates`。candidate的binding包含实际`host`、`placement`、
项目`code`、固定应用`python`、固定`resource_runtime`、CPU／内存边界及原资源租约。
成功请求复用PG结果，不为验收重复模型工作。无GPU模型推理的安装验线脚本为
`examples/verify_workspace.py`。

旧生产binding和仍在途请求不热改；目录迁移先登记owner／消费者，再切换、读回和退役。
WSL暂停要求已由用户2026-11-05的恢复通知撤回，部署按当次连通性和实际owner接续，
不自动重启已取消的fleet timer。
