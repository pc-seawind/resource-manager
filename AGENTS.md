# resource-manager 执行规则

- 本仓库独立Git管理，面向所有自有项目；不导入Visual Memory代码，不另建项目专属资源队列。
- 代码：ubuntu／office／WSL为`~/work/projects`，单／双5090为`~/sry/projects`；模型分别为`~/work/models`、`~/models`；数据分别为`~/work/data`、`~/sry/data`。
- 用`build.py`构建按commit固化的Python 3.12字节码runtime，`~/.local/bin/resource-manager`只链接构建产物；其他项目依赖runtime而非复制源码。
- 保留PG短事务仲裁、原主机租约、绝对截止和真实退出证明；未知owner不释放、不异机重推，不驱逐无关工作。
- 临时work只存可回收输入／缓存，唯一结果必须在PG或声明的正式项目数据位置保存；成功／失败结果收妥且物理退出后清理，丢ACK／执行未知先恢复原owner。
- 按契约实现，不加无依据的兼容／fallback；不重复校验自有结果，不扫描NAS，不使用并行助手代理。
- 改动须相关测试、commit、实际runtime构建／入口读回；部署不改运行中的请求／模型pin。WSL已于2026-11-05恢复，按当次连通性与原owner接续，不自动恢复已取消的fleet timer；补齐冻结runtime可用`deploy.py --host wsl --revision <pin>`，不为补机重跑其他主机成功工作。
- 节点本地化必须先封住旧中心对目标设备的新授予，再激活本地账本；不得让两个数据库各自授予同一物理设备。旧owner未知时不切换、不清理或异机重推。
