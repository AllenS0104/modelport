# 模港 ModelPort

云厂商无关的 **API Key 销售平台**：中文官网、模型价格与接入指南，以及统一客户/管理员控制台。客户在自己的 WorkBuddy、OpenClaw、支持自定义端点的 VS Code 扩展或应用中使用平台 Key。账户、额度、渠道和账本复用 New API；不提供网页聊天，不部署 GPU，不运行本地大模型，不把供应商原始 Key 交给客户。

**当前交付版本：`v2026.09.21.2`，已验证的修复候选，不代表已在现有生产或目标域名上线。** 当前交付范围为可迁移、可校验的单机部署包，不是已验收的公网商业服务。仓库和 Release 可公开分享源码及无数据应用包；绝不包含账户数据库、供应商凭据、客户 Key、会话密钥、日志或生产截图。

网站内容清理与调整方案：[中文 Markdown](docs/WEBSITE-CONTENT-PLAN.zh-CN.md)。旧 `v2026.09.21.1` 仅作历史归档，不包含当前 API-only、账户安全及上游缺陷修复，不应继续用于新部署。

## 交付结构

| 路径 | 用途 |
|---|---|
| `h5/` | 中文官网、公开模型/价格及开发者接入教程；旧聊天入口禁用 |
| `console/` | 品牌与安全页源码覆盖层；保留原生认证和账本 |
| `backend/` | 固定上游的限流、账户策略、API销售、上游缺陷补丁及Go回归 |
| `compose.yaml`、`nginx.conf` | 原始回环隔离部署基线；不直接作为公网配置 |
| `deploy/release.py` | 白名单打包、资源校验、离线 Docker 镜像导出 |
| `deploy/runtime.py` | 新环境初始化、离线镜像加载/校验、SQLite 在线备份 |
| `deploy/MIGRATION.zh-CN.md` | 重建、数据迁移、升级回滚与云上线条件 |
| `tests/` | 发布工具单元测试和隔离账户/计费/会话/UI 回归 |
| `docs/WEBSITE-CONTENT-PLAN.zh-CN.md` | 目标网站内容盘点、保留/移除规则、导航及分阶段上线方案 |
| `release-lock.json` | 当前发布的完整文件哈希、镜像、平台和版本清单 |
| GitHub Release 附件 | 完整应用包、镜像、已构建前端、对应源码与 SHA256SUMS |

`version-lock.json` 记录原始上游基础镜像；**实际运行的是带补丁的维护镜像**，以 `release-lock.json` 及包内 `backend-dist/build-manifest.json` 为准。不要用官方 `latest` 替换。

Docker 导出指定平台后，原始 OCI 索引 ID 与导入后的平台镜像 ID 可能不同。发布清单同时记录原始 ID、导出 manifest、配置与层摘要，由 `runtime.py check-images` 校验，不能只比较一个原始 ID。Git 使用 `.gitattributes` 保留原始字节，避免自动换行转换破坏来源哈希或 CSP。

保留的关键修复：

- 登录、注册和敏感验证仍为每来源 IP 20 次/1200 秒；刷新、退出各自独立 120 次/60 秒。
- 账户登录状态与官网/H5 入口同步，无会话提示的公开页不发送多余恢复请求。
- 普通用户账户安全仅保留密码操作，既有登录验证不降级；Nginx和后端都禁止自助删号，客户销售Key不受该设置限制。
- 默认中文、API-only导航、模型派生条目删除与邮件设置/测试入口；生产邮件仍须配置SMTP并验证实际收件。
- Gemini `countTokens`明确拒绝、不生成不计费；没有实现计数功能。
- Gemini截断向Chat/原生Gemini/Claude/Responses发出明确流错误，保留部分用量结算，不假装正常结束或重试。
- 流式末帧保留结束原因和工具调用；阿里多图逐张返回；任务提交接受200/201/202并继续原解析及持久化流程。
- Responses转Chat时非文本工具输出明确拒绝，提示使用原生Responses渠道；不是新增Chat多模态工具消息能力。

付款履约当前由管理员审核并开通额度/模型分组，没有自动收款或自动开通系统。软件兼容不等于每个供应商模型都已接通：真实供应商出站、地区、模型权限/配额及外部SMTP需要在目标环境另行验收。

## 使用发布包（推荐）

目标环境：**Linux x86-64、Python 3.12+、Docker Engine 28+、Docker Compose 插件**，本地持久化磁盘。首发演练使用 Engine 29 / Compose 5。至少预留 2 vCPU、2 GiB 可用内存及镜像/备份空间；实际容量按业务压测确定。不支持将 SQLite WAL 放到 NFS/SMB/Azure Files，也不支持 SQLite 多副本。

从公开仓库 Release 下载同一版本的三个附件。以下示例使用 `v2026.09.21.2`：

```sh
gh release download v2026.09.21.2 --repo AllenS0104/modelport \
  --pattern 'modelport-*.tar.gz' --pattern SHA256SUMS --pattern release-manifest.json
sha256sum --check SHA256SUMS
mkdir modelport-v2026.09.21.2
tar -xzf modelport-v2026.09.21.2-linux-amd64.tar.gz -C modelport-v2026.09.21.2
cd modelport-v2026.09.21.2/modelport
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

Git 仓库保存维护源码；大型二进制不进 Git，位于经过发布检查的 Release。发布包另外包含已构建控制台与完整上游对应源码，无需在目标机重新编译。

如需从源码重建，见 `deploy/MIGRATION.zh-CN.md`。不要从运行目录整体 `git add .`；先用白名单导出工具建立干净源码目录。

```sh
python3 -m unittest discover -s tests -p 'test_release.py' -v
python3 deploy/release.py export-source --output /absolute/path/to/new-source-directory
```

## 许可证与来源

基于 [QuantumNous/new-api](https://github.com/QuantumNous/new-api) `v1.0.0-rc.37`，固定提交 `385d2dfd10d821b25c8a6766bd16eea248cb1652`。保留 `LICENSE.new-api`、`NOTICE.new-api` 和第三方许可证；前端仍显示原作者署名及原项目链接。

**公开仓库也不能替代运行版本的准确对应源码。** 发布包保留可从页脚下载的 `console-dist/modelport-source.tar.gz`，含固定上游源码、前后端覆盖层及构建说明。修改后须同步重建对应源码包，保持AGPL义务、许可证和原作者署名；公开发布永远不包含真实业务数据或秘密。
