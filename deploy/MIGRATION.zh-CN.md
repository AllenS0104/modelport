# 迁移、重建与运维

## 边界

本项目初期采用单台 Linux 主机 + Docker Compose + 本地持久化磁盘。可迁入阿里云、Azure 或其他支持 Docker 的 Linux VM；尚未选择云账户、地区、预算、域名或创建云资源。不要把“应用包已可恢复”解释为“公网支付与商业运营已验收”。

应用包不含业务数据。真正迁移有三类输入：同版本应用包、SQLite 一致性备份、受保护的环境秘密及外部配置。任何一类缺失都不能声称现有客户已经完整迁移。

## 现有数据备份

运行库为原部署目录下 `data/one-api.db`，可能存在活跃 WAL。**不要只复制主 `.db` 文件。**

```sh
umask 077
mkdir -m 700 /protected/modelport-backup
python3 deploy/runtime.py backup \
  --database /path/to/current-deployment/data/one-api.db \
  --output /protected/modelport-backup/one-api.snapshot.db
```

脚本通过只读 SQLite 连接执行在线 backup，验证完整性，拒绝覆盖现有输出。必须使用新的输出文件名；需要长期保留时，用组织批准的加密备份系统保存，并验证可解密恢复。脚本本身**不执行加密、不上传数据**。

备份包含用户密码哈希、客户 Key、渠道凭据、余额、账本等敏感信息；不上传 GitHub，即使仓库 Private。环境秘密单独保管。业务数据库与 `.runtime.env` 都应纳入受控备份，不能只有应用包。

## 数据迁移与切换

1. 在新主机解压同版本包，校验，导入镜像并初始化运行目录；不要启动新后端，不执行 `/setup`。
2. 维护窗口暂停入口及业务写入，等待请求排空，优雅停止旧后端（至少 130 秒超时）；做最终一致性备份，记录源库 SHA256 和关键业务表数量。不运行两个可写副本。
3. 通过受控加密通道传输备份和既有稳定秘密；校验哈希。目标必须是空数据目录，不能覆盖已运行环境。
4. 使用同一个 backup 命令，从已验证的快照复制到新目录 `data/one-api.db`；它会拒绝覆盖，完成后检查数据文件属主为 UID/GID 1000、权限 0600。以 root 复制时需 `chown 1000:1000 data/one-api.db`。
5. 将**原有稳定** SESSION_SECRET 和 CRYPTO_SECRET 安全注入目标 `.runtime.env`，不要在命令行、工单、提交或日志中打印。新环境初始化生成的秘密只适用于全新空库，不能假定能解密旧业务数据。
6. 先只通过回环/SSH 隧道启动，核对管理员、用户、渠道、客户 Key、余额/账本和后台任务。用专门验收账户检查登录/退出/切换与 SSE；付费模型调用必须单独授权。
7. 验收后切流。保持旧系统停止写入并保留受保护备份；失败时停止新写入，再决定回切。若新环境已有交易，禁止直接倒灌旧库覆盖新账本。

**既有原型的已知限制：** 历史运行未配置持久 SESSION_SECRET，CRYPTO_SECRET 默认可能由其派生。应用发布包无法恢复进程中未保存的随机秘密。迁移前必须核实已启用功能对这些秘密的依赖；不能承诺保留旧登录会话或未核验的加密字段。必要时安排重新登录及受影响安全凭据的受控重新绑定，不提取进程内秘密、不通过清库规避问题。

## 云上正式启用前

- 确认云账户、预算、区域、域名、备案/合规要求、上游采购授权和使用条款。
- 配置 TLS、Secure Cookie、严格 Origin 与域名 allowlist；原回环 HTTP 配置不得直接公网暴露。
- 明确信任的负载均衡/反代链，保证真实客户端 IP 正确且不可伪造。当前 `TRUSTED_PROXIES=none` 可能将多个用户视作同一来源；不可简单改成信任全部 X-Forwarded-For。
- 评审模型供应商、DNS 和必要外部认证的出网策略。当前内部 Docker 网络默认不能访问外部供应商；不得为图方便暴露后端 3000 端口或任意内网服务。
- 保留自删禁令、会话限流、登录保护、密码/MFA/权限和账本机制。
- 稳定秘密注入、备份加密与异地保留、恢复演练、容量/费用上限、指标告警、日志脱敏与保留策略。
- 验证实际 HTTPS 下的多轮 SSE、取消、超时、退款/扣费一致性、跨账号隔离、登录限流及真实 Key 撤销。
- SQLite 只用于单实例本地磁盘；迁到托管 MySQL/PostgreSQL 或多副本需单独设计和验证数据迁移，不能仅修改连接串。

`prepare_domain.py` 仅生成不启用的域名草案，不自动申请证书、不改变活跃配置：

```sh
python3 deploy/prepare_domain.py \
  --origin https://models.example.com --output deploy/my-domain-draft
```

草案基于原始 `compose.yaml`，不是对 `compose.runtime.json` 的可直接叠加生产方案；运行路径、秘密注入与反代链需要在正式云部署时统一审查。不得把草案生成成功当成公网验收完成。

## 从固定源码重建

原型维护代码与上游 Git 树分开保存，避免污染或意外升级：

```sh
git clone --no-checkout https://github.com/QuantumNous/new-api.git upstream
git -C upstream checkout --detach 385d2dfd10d821b25c8a6766bd16eea248cb1652
python3 console/build.py --prepare-only
cd .console-build/web
npm exec --yes --package=bun@1.4.2 -- bun install --frozen-lockfile
cd ../..
python3 console/build.py
# 新的离线构建目录中操作，不覆盖在线目录：
cp -a .console-build/web/dist console-dist
python3 backend/build.py
```

Python 3.12+，Node 22/npm，Bun 1.4.2。Go 使用 `backend/Dockerfile` 固定构建器，不要求主机安装 Go。上游必须为指定提交且干净，不能将下载的无 Git 源码快照冒充已验证 Git 工作树。后端构建含 Go 限流测试和两条路由实际接线检查。

重建后应运行真实隔离回归（所需 Playwright 及浏览器仅安装在验收环境）：

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 deploy/release.py seal-build
python3 tests/domain_preparation.py
```

专项限流测试验证生产默认 20/1200；综合 UI/计费测试的临时 fixture 使用更大的关键请求额度，不能代替专项测试。均不得使用生产数据库或真实供应商 Key。

`seal-build` 仅允许在不含 `data/` 的离线构建目录运行，核对来源后自动执行专项限流和综合集成回归；成功后关联控制台 manifest 的 `backend_image_id`，同步完整对应源码包及哈希。不能随意手工改哈希掩盖文件变化。当前已运行历史产物已具备此关联。

```sh
python3 deploy/release.py build --version v2026.09.21.1 \
  --output /path/to/new-release-directory
```

版本输出目录必须不存在。发布器只收集源码白名单与控制台 manifest 中的资源，验证后端来源和镜像版本；不会打包业务数据、现场日志、历史交接材料或机器登录脚本。输出 `source/`（适合 Git）、`modelport/`（展开的离线包）、压缩包、清单、SHA256SUMS。

新版本使用新标签，不覆盖旧发布。先在新的独立目录/端口用空库演练，再发布 Private Release；GitHub 自动生成的 Source code zip **不含**完整部署所需镜像与前端产物，请下载自定义应用附件。

## 升级与回滚

升级前留存旧应用包、对应配置、受保护秘密和在线数据库备份。新版本先用隔离库验收；读取上游数据库迁移说明。正式切换时保留原业务挂载，维护窗口内优雅重建 API 后重建/reload ingress（Nginx 可能缓存旧容器 IP）。

若只回滚代码/前端，保持新交易数据和既有安全策略；不盲目恢复数据库快照。跨数据库结构版本回滚需单独演练并确认可逆。控制台更新应保留旧哈希资源，直到旧页面退出；现场升级不能直接删除整棵 `console-dist/`。

应用容器可重建，数据和秘密不可随容器生命周期删除。任何新的入口都必须经过含删号禁令的受控 ingress。发布和迁云不涉及 OpenClaw、飞书或其他机器上不相关服务。
