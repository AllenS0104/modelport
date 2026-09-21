# 后续域名部署准备（未启用、不是公网链接）

## 2026-09-18：阿里云 / Azure 通用适配准备

**本轮只准备应用与配置，不选择或创建云资源，不绑定域名，不改当前回环隔离。** 云厂商、账号/订阅、区域、域名、预算和正式发布审批仍待确定。不是已经完成 Azure 部署准备流程或公网 TLS 验收；选定 Azure 目标后需单独完成架构审批、验证及部署。

工作名为“模港 ModelPort”，仅是可更改的 UI 名称，未核查商标/域名。`h5/index.html` 的 `body[data-brand]` 是展示名来源；New API 的原生品牌设置待管理员初始化后另行配置。保留上游署名与许可证，不改 Compose 项目名或数据路径。

### 已准备的应用层能力

- 官网、用户工作台、API 和原生会话保持**同源、根路径部署**。导航与请求使用相对地址，不需要为阿里云/Azure分叉前端。
- 客户接入地址从当前安全 `location.origin` 计算 `/v1`，不再写死 `127.0.0.1:13000`。非回环 HTTP 不生成可发送凭据的地址，不因换域名自动宣布可交易。
- `/h5/#guide` 提供 Python SDK、Node.js fetch 和 cURL 教程与下载文件；示例读取环境变量，Python/Node 不回退到默认供应商、不自动重试或跟随跳转。
- 固定 New API/Nginx 镜像、现有 SQLite 持久卷和 SSE 代理能力继续复用。现有登录/MFA/账本不另造。

### 不启用的域名草案生成器

在目标 Linux 项目目录运行以下**草案生成命令**（`.invalid` 是不可用的示例域名）：

```sh
python3 deploy/prepare_domain.py \
  --origin https://models.example.invalid \
  --output deploy/domain-draft
```

输出仅写到新的 `deploy/` 子目录，目录已存在则拒绝覆盖；不会调用 Docker、修改活跃文件或启用入口：

| 文件 | 用途与边界 |
|---|---|
| `backend-nginx.conf` | 在现有 Host 白名单追加明确域名；保留当前严格 CSP/SRI、API 路由、SSE 与回环健康检查 |
| `tls-nginx.conf.example` | 同机 TLS 反代草案，正确区分普通 HTTP/WebSocket Connection；拒绝错误 Host，保留客户端端口；证书路径仍故意不可用 |
| `compose.domain-draft.json` | 非自动加载的 Compose 覆盖草案：Secure Cookie、精确可信 HTTPS Origin，强制从受保护环境注入稳定 SESSION_SECRET；不开放端口或出网 |
| `readiness.json` | 来源哈希、域名和未完事项，始终标为 `approved_for_production=false` |

生成器仅接受精确 HTTPS origin（ASCII/punycode 主机名及可选端口），拒绝 IP、通配符、路径、用户信息、查询、片段、换行和配置注入。它不查询 DNS、不签发证书、不证明域名归属或站点可达。修改前端、Compose 或 Nginx 后应重新生成并重新审查，不能沿用旧 CSP 草案。

生成文件中的 bind mount 指向生成时的本机绝对路径，因此应在迁移后的目标 Linux 主机重新生成，不要把 Windows 路径或其他机器的生成产物直接当作部署配置。

`SESSION_SECRET` 不写入生成文件；真实部署时通过受保护的秘密注入机制提供。不要把包含已展开秘密的 `docker compose config` 输出粘贴到日志或聊天；配置检查应使用 `--quiet`。尚未注入变量时草案应校验失败，而不是用默认秘密启动。

### 两类后续部署路径

| 路径 | 阿里云 / Azure 对应候选 | 必须满足的条件 |
|---|---|---|
| 单台 Linux 容器主机 | ECS / Azure Linux VM | 可沿用当前单实例 Compose。数据放在受保护的持久磁盘，在线备份并演练恢复；不能只复制活跃 WAL 主文件 |
| 托管容器或多副本 | ACK / AKS、Azure Container Apps 等 | 不能直接把现有 SQLite 放在容器临时盘，或默认通过共享文件系统扩容。先评估外部数据库、缓存、一致会话秘密及多副本原生兼容性，再生成各云的 IaC |

当前 SQLite 使用 WAL；SQLite 官方明确 WAL 不适用于网络文件系统。不能把 Azure Files、NFS 或 SMB 共享当成本机数据盘直接迁移现有数据库，即使共享本身是“持久存储”。托管容器方案应先完成数据库选型与迁移/恢复验收。

选择云和区域后再确定：同源 HTTPS 入口、域名与证书、私网连接、精确可信代理范围、供应商受控出网、数据备份、日志保留、监控告警、速率与成本上限。当前 `TRUSTED_PROXIES=none` 是保守设置，不能在未核查实际代理链前改成通配；否则客户端 IP、限流与审计可能失真。

原生 `SESSION_COOKIE_SECURE=true` 必须同时配 `SESSION_COOKIE_TRUSTED_URL` 精确 HTTPS origin，不能只改前端域名。TLS可能在外层结束，内层仍HTTP；可信Origin是原生认证设置，不可用客户端任意 `X-Forwarded-*` 代替。核对原生公开站点URL、OAuth/Passkey等回调配置；不要用 `CORS *` 解决跨域登录问题。

SSE 需关闭代理缓冲，并检查云负载均衡/网关的连接与空闲超时是否适配现有180秒请求边界。入口可访问不等于模型供应可用，不自动解除内部网络隔离。公网之前先完成私下初始化、真实限额调用和账务验收；不能暴露未初始化 `/setup`。

区域与备案：在中国内地对外提供网站服务，先核对ICP备案等要求；其他地域也应核查适用的备案、数据处理与服务条款，不能据此承诺无需合规。Azure全球与中国区的账号、服务和区域支持需要按最终选择单独确认。

### 验证范围与资料

`tests/domain_preparation.py` 检查恶意/无效origin拒绝、草案不改活跃文件、Compose合并后仍回环与内部网络、临时证书下的Nginx语法。`tests/domain_compatibility.py` 以浏览器路由模拟HTTPS域名（**不是实际DNS/TLS**），并用无网络、独立数据库的原生容器核对安全Cookie模式的Origin拒绝。实际域名证书链、云网络、代理链、真实账务、告警与备份恢复仍未验收。

官方资料：
- [OpenAI Python SDK：base_url、环境变量及重试](https://github.com/openai/openai-python)
- [Azure Container Apps 存储生命周期](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)
- [SQLite WAL 的同机与网络文件系统限制](https://www.sqlite.org/wal.html)
- [阿里云：不同场景下的备案要求](https://help.aliyun.com/en/icp-filing/basic-icp-service/product-overview/faq-about-icp-filing-applications-in-different-scenarios)

以下为早期草案说明；新增加的自动生成工具与约束以本节为准。

当前入口仅 `127.0.0.1:13000`，没有 LAN 或公网地址。H5 位于 `/h5/`；原生后台保持自己的路由。远程手机目前只能看交付的截图或离线 HTML，不能直接用此回环地址访问服务器。

本目录给出 **现有受控 HTTPS 入口位于同一服务器时** 的反代配置样稿 `domain-nginx.conf.example`。使用保留的 `.invalid` 域名防止误认为有真实域名。证书路径是占位符，不存在，不会启动；不能复制后直接重载系统 Nginx。

启用前依次完成：

1. 决定正式主机、域名、DNS 与证书，核对已有入口配置；不覆盖已有服务。
2. 本人完成管理员安全初始化。正式客户开放前，关闭不必要注册/奖励或配置邮件验证与防滥用；完成登录后额度、Key、供应故障退款验收。
3. 将示例域名/证书路径改为实际值，在审批范围内合并至已有 HTTPS 入口；不要给新公网映射直接开放原始 HTTP。
4. 在本项目 `nginx.conf` 的本机服务 `server_name` 中追加已批准的实际域名，否则当前 Host 白名单会拒绝。不要改成任意 Host 通配。
5. 在正式应用配置启用 `SESSION_COOKIE_SECURE=true`，设置 `SESSION_COOKIE_TRUSTED_URL=https://实际域名`（精确 HTTPS origin），按实际代理链设置可信代理。示例代理不自动替代这些应用安全设置。
6. 会话密钥通过受保护托管方式设置，不能写入此目录、Compose 或命令行；当前随机会话值只适合本地验证。生产多实例需一致的安全密钥与数据库/缓存方案。
7. 真实 API 出网必须单独批准并限制目标；本地应用仍 internal 网络。不要因为域名入口通了就宣称供应端已接通。
8. 在隔离副本验收 HTTPS、Cookie、跨域/CSRF、WebSocket/SSE、请求超时、日志脱敏，再发布给客户。支付仍保持未配置。

如果 HTTPS 入口不在同一服务器，127.0.0.1 后端地址不成立；应设计受保护的私网连接/隧道，不擅自开放 LAN 或公网后端端口。

**此方案未执行 DNS/TLS/公网验收，未改系统 Nginx、OpenClaw、系统服务或防火墙。**
