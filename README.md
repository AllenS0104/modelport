# 模港 ModelPort

云厂商无关的模型 API 平台：官网、模型价格页、H5 聊天工作台，以及统一客户/管理员控制台。账户、客户 Key、额度、渠道和账本复用 New API；不部署 GPU，不运行本地大模型。

**当前交付范围：可迁移、可校验的单机部署包，不是已验收的公网商业服务。** 仓库不含账户数据库、渠道凭据、客户 Key、会话密钥、日志或生产截图。GitHub 仓库及 Release 应始终保持 Private。

## 交付结构

| 路径 | 用途 |
|---|---|
| `h5/` | 官网、公开模型/价格、开发者教程与聊天工作台 |
| `console/` | 品牌与安全页源码覆盖层；保留原生认证和账本 |
| `backend/` | 固定上游的会话限流补丁、Go 测试、构建器 |
| `compose.yaml`、`nginx.conf` | 原始回环隔离部署基线；不直接作为公网配置 |
| `deploy/release.py` | 白名单打包、资源校验、离线 Docker 镜像导出 |
| `deploy/runtime.py` | 新环境初始化、离线镜像加载/校验、SQLite 在线备份 |
| `deploy/MIGRATION.zh-CN.md` | 重建、数据迁移、升级回滚与云上线条件 |
| `tests/` | 发布工具单元测试和隔离账户/计费/会话/UI 回归 |
| `release-lock.json` | 当前发布的完整文件哈希、镜像、平台和版本清单 |
| GitHub Release 附件 | 完整应用包、镜像、已构建前端、对应源码与 SHA256SUMS |

`version-lock.json` 记录原始上游基础镜像；**实际运行的是带补丁的维护镜像**，以 `release-lock.json` 及包内 `backend-dist/build-manifest.json` 为准。不要用官方 `latest` 替换。

Docker 导出指定平台后，原始 OCI 索引 ID 与导入后的平台镜像 ID 可能不同。发布清单同时记录原始 ID、导出 manifest、配置与层摘要，由 `runtime.py check-images` 校验，不能只比较一个原始 ID。Git 使用 `.gitattributes` 保留原始字节，避免自动换行转换破坏来源哈希或 CSP。

保留的关键修复：

- 登录、注册和敏感验证仍为每来源 IP 20 次/1200 秒；刷新、退出各自独立 120 次/60 秒。
- 账户登录状态与官网/H5 入口同步，无会话提示的公开页不发送多余恢复请求。
- 原生安全页移除自删入口，Nginx 拒绝 `DELETE /api/user/self`；后端端口不得公开。
- 官网、聊天、客户及管理员界面统一品牌；不创建第二套账户。

## 使用发布包（推荐）

目标环境：**Linux x86-64、Python 3.12+、Docker Engine 28+、Docker Compose 插件**，本地持久化磁盘。首发演练使用 Engine 29 / Compose 5。至少预留 2 vCPU、2 GiB 可用内存及镜像/备份空间；实际容量按业务压测确定。不支持将 SQLite WAL 放到 NFS/SMB/Azure Files，也不支持 SQLite 多副本。

从私有仓库 Release 下载同一版本的三个附件。以下示例使用 `v2026.09.21.1`：

```sh
gh release download v2026.09.21.1 --repo AllenS0104/modelport \
  --pattern 'modelport-*.tar.gz' --pattern SHA256SUMS --pattern release-manifest.json
sha256sum --check SHA256SUMS
mkdir modelport-v2026.09.21.1
tar -xzf modelport-v2026.09.21.1-linux-amd64.tar.gz -C modelport-v2026.09.21.1
cd modelport-v2026.09.21.1/modelport
python3 deploy/release.py verify
python3 deploy/runtime.py load-images
python3 deploy/runtime.py init --project modelport-staging --port 13000
docker compose --env-file .runtime.env -f compose.runtime.json up -d --wait
```

初始化以 Linux UID 1000 或 root 运行；容器固定 UID 1000，数据目录 0700。若以 root 初始化，后续需同样有权读取受保护的 `.runtime.env`。初始化不会覆盖已存在的数据或秘密；自动生成持久 SESSION_SECRET / CRYPTO_SECRET，权限 0600，**不会输出秘密**。镜像使用发布专属标签，不覆盖原部署标签。

仅在 `http://127.0.0.1:13000/` 监听。远程服务器请通过自己的 SSH 隧道访问；首次新装在 `/setup` 私下创建管理员，无默认账户密码。迁移既有账户时**不要重新初始化管理员**，按迁移文档恢复数据库。

```sh
docker compose --env-file .runtime.env -f compose.runtime.json ps
curl --fail http://127.0.0.1:13000/api/status
curl -i -X DELETE http://127.0.0.1:13000/api/user/self
# 上一个请求应为 403 / SELF_ACCOUNT_DELETION_DISABLED。
docker compose --env-file .runtime.env -f compose.runtime.json down --timeout 130
```

`down` 不删除宿主机数据。禁止用 `down -v`、删数据库或重做 setup 来“解决”已有环境的问题。`compose.runtime.json` 含初始化时的绝对挂载路径；初始化后不要移动目录。需要移动时，在新位置重新准备运行配置并按迁移流程保留数据和秘密。

默认仍限制供应商出网，仅用于安全恢复/演练；不是可立即收费的公网部署。上云前必须逐项完成迁移文档中的 TLS、可信反代、稳定秘密和供应出网验收。

## 开发与构建

Git 仓库保存维护源码；大型二进制不进 Git，位于 Private Release。发布包另外包含已构建控制台与完整上游对应源码，无需在目标机重新编译。

如需从源码重建，见 `deploy/MIGRATION.zh-CN.md`。不要从运行目录整体 `git add .`；先用白名单导出工具建立干净源码目录。

```sh
python3 -m unittest discover -s tests -p 'test_release.py' -v
python3 deploy/release.py export-source --output /absolute/path/to/new-source-directory
```

## 许可证与来源

基于 [QuantumNous/new-api](https://github.com/QuantumNous/new-api) `v1.0.0-rc.37`，固定提交 `385d2dfd10d821b25c8a6766bd16eea248cb1652`。保留 `LICENSE.new-api`、`NOTICE.new-api` 和第三方许可证；前端仍显示原作者署名及原项目链接。

**Private 仓库不免除 AGPL 对实际网络用户的对应源码提供义务。** 发布包保留可从页脚下载的 `console-dist/modelport-source.tar.gz`，含固定上游源码、前后端覆盖层及构建说明。修改后须同步重建对应源码包；不可让用户下载链接只指向他们无权访问的 Private 仓库。
