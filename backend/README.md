# New API Go 维护补丁

固定上游 `385d2dfd10d821b25c8a6766bd16eea248cb1652`（QuantumNous/new-api v1.0.0-rc.37）。保留 Go 后端，不迁移 JS、不修改原始 `upstream/`、不新增账户/账本。

## API Key 销售模式

`api-sales.patch` 关闭会话网页聊天 `/pg`，保留客户 Key 的 `/v1` 接口。当前默认构建为独立候选 `modelport-new-api:upstream-bugfixes-v1`；现有生产 `api-sales-v1` 不自动切换，发布状态以发布证据和运行容器为准，不以镜像存在判断上线。

- 普通客户控制台默认中文，常规菜单仅有数据看板、概览、API 密钥、使用日志、任务日志；审计日志保留给管理员。
- `POST /api/models/channel-only/delete` 仅供管理员处理没有元数据 ID 的渠道派生模型，确认后事务性移除所有渠道内的精确名称及对应路由能力；不删除其他模型、渠道密钥、客户余额或价格。已有元数据继续走原生删除接口。
- `GET /api/user/notification/email` 返回 SMTP 与保存收件地址的配置状态；`POST /api/user/notification/email/test` 复用真实通知服务与限流，仅发送到服务器保存的地址。未配置、无收件人或发送失败均明确报错。
- `tests/api_sales.py` 使用独立 SQLite、渠道供应商与 SMTP 接收端，验证中文菜单、模型删除、客户 API 授权及精确计费、通知保存和真实低余额邮件。
- 当前生产 SMTP 尚未配置，后端隔离网络禁止外部出站。测试环境邮件送达不代表真实外部邮箱可收件；正式邮件需通过安全配置界面设置获准 SMTP 并单独验证网络和实际收件。不要在聊天或 Git 中存放 SMTP 密码。
- 购买履约目前由管理员核验付款后设置用户分组、模型权限和额度，再由客户管理自己的 Key；未新增自动收款或订单开通系统。

## 上游缺陷维护补丁（2026-09-21）

`upstream-bugfixes.patch` 在固定版本上修复以下明确问题，不执行上游全量升级：

- Gemini `:countTokens` 在 `/v1/models/` 与 `/v1beta/models/` 经鉴权后、选渠道/计费前明确404拒绝，避免误执行生成并扣费。**这是拒绝未支持操作，不是新增计数功能。**
- Gemini 传输截断会向客户发出协议对应的流错误，不再追加正常DONE/完成帧；覆盖Chat、Gemini原生、Claude、Responses。保留已返回部分usage的既有结算，不重新请求上游、不因已输出部分答案而整体退款；真实客户端断开后不尝试正常收尾。已发出的HTTP200不可改成502，以SSE错误事件表达失败。
- 显式`include_usage=false`不再丢掉同时携带usage的结束帧、tool_calls或其他choice；只过滤真正的usage-only帧。
- Responses→Chat的纯文本工具结果继续转换；含图片/文件/音频等非文本内容的工具结果明确拒绝，提示使用原生Responses渠道，而非把base64冒充文本发送。**这不等于为Chat协议实现多模态tool消息**，原生Responses转发不受该限制影响。
- 阿里单choice多图逐张保留，不再只交付末图；不生成空图片条目。
- 任务提交允许200/201/202继续经过原解析、持久化与结算链路；其他状态仍拒绝，合法HTTP状态不能绕过任务内容解析。

新增Go回归随构建运行；完整HTTP/账本回归使用一次性数据库、假供应商、假Key与SMTP，不触及生产：

```sh
python3 backend/build.py --console-dist console-dist --work-dir .backend-bugfix-candidate
python3 tests/api_sales.py --api-image modelport-new-api:upstream-bugfixes-v1 --site-root . --console-dist console-dist --extended-scenarios --upstream-issues --output evidence/upstream-bugfixes
```

以结果中的镜像ID及`all_scenarios_passed`、`all_upstream_issue_checks_passed`判断，不只看`completed`。其他尚未确认的上游issue不因此视为已修；真实供应商和外部SMTP仍需独立验收。

## 账户安全限制（2026-09-21）

`account-security.patch` 和 `overrides/middleware/account_security_policy.go` 复用 `UserAuth` / `TryUserAuth` 注入的服务端角色（用户库/有效会话或 PAT），对普通用户的安全设置写接口加管理员门槛。管理员仍经过原生证明、作用域、会话、权限及限流检查，并非直接放行。前端隐藏项包括绑定、会话管理、控制台访问令牌 PAT、MFA、Passkey 和隐私；**客户销售 API Key `/api/token` 与钱包接口不在此限制内**。

- 只限制 MFA 设置/启用/停用/重置恢复码，以及 Passkey 注册/删除；登录和安全证明验证不封。
- OAuth 只限制 `intent=bind`，对已创建的绑定回调重新检查角色；登录及 `intent=verify` 保留。旧 Telegram widget 接口原本为410，仍不恢复。
- 共用 `PUT /api/user/setting` 只拒绝改变 `record_ip_log`；未传/null 保留原值，原值回传允许，通知等非本次范围设置仍按上游处理。
- `GET/PUT /api/user/self` 保留；密码修改和首次设密复用原安全证明/验证与会话撤销语义。`DELETE /api/user/self` 增加后端同码403兜底，原 Nginx 禁令不移除。
- 不清除或停用已有认证因子、绑定、会话或 PAT；读取状态、登录挑战、找回密码、refresh、logout 保留。

接口清单、验收边界及未实测部分见 `../ACCOUNT-SECURITY-RESTRICTIONS.zh-CN.md`。账户安全版本已于 2026-09-21 部署；API 销售版本继续保留上述限制。

## 会话限流（保留原补丁）

`auth-session-limits.patch` 只替换刷新和退出两条路由的限流器，不改变认证、Cookie、密码、安全证明、账本或数据库结构。

- 登录、注册、安全验证等仍使用原有 `CriticalRateLimit`，当前为每来源 IP 20 次 / 1200 秒；用户级敏感操作限制不变。
- `POST /api/user/auth/refresh` 和 `POST /api/user/auth/logout` 各自使用独立的每 IP 120 次 / 60 秒限额，互不挤占，也不消耗登录防刷额度。
- 会话限额持续生效，超限返回429及 `Retry-After`。不使用 Cookie 值、用户名或可伪造请求头作为绕过限流的依据。
- 本地 SSH 隧道仍可能把多个浏览器/账户视为同一来源；我们不伪造来源 IP，也不开放对任意代理头的信任。未来公网部署须单独配置并验证可信代理链。

## 构建和验收

项目根目录需要干净的固定 `upstream/`、按 `console/README.md` 构建的 `.console-build/web/dist` 和 Docker。不要覆盖正在挂载的 `console-dist/`：

```sh
python3 backend/build.py
python3 tests/account_security_restrictions.py --api-image modelport-new-api:upstream-bugfixes-v1 --console-dist console-dist --output evidence/upstream-bugfixes-account-security
python3 tests/auth_session_limits.py --api-image modelport-new-api:upstream-bugfixes-v1 --output evidence/upstream-bugfixes-session-limits
# 多次构建请指定新的项目内专用目录，原目录不自动清理：
# python3 backend/build.py --work-dir .backend-security-final
```

构建在专用 `.backend-build/`（可用 `--work-dir` 指定新的 `.backend-*` 目录）中展开上游快照并按序应用四份补丁，使用上游锁定的 Go 构建镜像。先执行限流、策略、上游缺陷及选定的密码/登录挑战/Passkey 回归，再编译并基于原官方镜像替换 `/new-api` 二进制。输出独立候选镜像 `modelport-new-api:upstream-bugfixes-v1`，以及 `backend-dist/upstream-bugfixes-v1/build-manifest.json` 和对应 `modelport-source.tar.gz`。清单绑定前端产物清单哈希；源码包含原始上游、前后端维护层和专项测试（含供应商fixture依赖），不含数据库或凭据。`--image` / `--console-dist` / `--output` 可显式指定候选产物，不自动部署、不上传、不修改 `upstream/` 或旧生产镜像标签。

发布前确认镜像 ID 与清单一致；备份配置、前端资源清单，并通过 SQLite 在线备份接口备份数据库。更新 H5 精确 CSP、对应源码包及资源清单后，再用 Compose 重建 API 服务并 reload ingress。当前没有配置稳定 SESSION_SECRET，重启可能需要重新登录，不承诺旧会话持续有效；不为恢复会话去提取进程内秘密。用户、客户 API Key、额度和账本不能因修复被重建或清空。

回滚恢复前一版镜像和配置，不覆盖期间新增业务数据，不解除现有自助删号禁令。对外仍只能通过 ingress，后端端口不得直接暴露。AGPLv3、原作者署名和对应源码下载要求继续适用；镜像内 `/licenses/modelport-backend` 同时提供维护补丁。

参照 OWASP Authentication / Session Management Cheat Sheets：不以放大或关闭登录防刷来解决会话恢复问题，不把浏览器提示 Cookie 当成身份验证，不改变会话旋转、撤销及敏感操作二次验证。
