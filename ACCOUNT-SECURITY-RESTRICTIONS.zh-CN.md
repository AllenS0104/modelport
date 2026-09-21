# 模港 ModelPort：普通用户账户安全限制

日期：2026-09-21。**14:23 已按用户“上线”授权部署到原站点。** 下方原隔离验收记录保持；当前上线证据为 `evidence/account-security-release.json`。

本次仅收紧账户安全页，不重写整个用户导航。沿用 New API Go 后端、原生账户/权限/计费系统；固定上游 `385d2dfd10d821b25c8a6766bd16eea248cb1652`，`upstream/` 保持原始干净，保留 QuantumNous/New API、AGPLv3、NOTICE 及对应源码下载。

## 1. 实际行为

- 普通用户 `/security` 只挂载原生密码卡片；不挂载绑定、会话管理、控制台访问令牌 PAT、Passkey、MFA、隐私或删号组件，不再由这些组件发起请求。
- 密码操作复用原生表单、作用域证明、当前密码校验与会话旋转。已有密码显示“修改密码”；无本地密码的 OAuth 用户仍沿用原生“设置密码”及身份验证流程，不凭现有会话直接设密。
- 管理员仍显示原安全组件，继续经过上游角色/权限、安全证明、会话与限流检查；没有赋予客户端新管理权。
- 个人菜单“退出”保留并实测；只移除安全页的会话管理卡片，不把 logout 当成禁止的设置写操作。
- 不清除、不停用任何已有 MFA、Passkey、绑定、恢复码或 PAT。登录时的强认证要求继续生效；不存在通过隐藏设置取消挑战的逻辑。
- 改密撤销语义不变：当前会话按原机制推进版本，其他会话及旧访问凭证失效；未放宽认证或恢复。

## 2. 服务端最小限制

复用 `UserAuth` / `TryUserAuth` 验证会话或 PAT，并从服务端用户记录写入角色。新增策略仅检查此上下文的 `id` 和 `role >= RoleAdminUser`，不信任 body/query/header/前端 store 的管理员声明。Casbin 现有注册项没有账户自助安全设置的独立权限；本次不新建另一套授权系统或增加可分配权限。

普通用户被限制时返回 **HTTP 403**，稳定错误码 `ACCOUNT_SECURITY_MANAGED_BY_ADMIN`：

| 范围 | 受限接口/操作 |
|---|---|
| 会话管理 | `DELETE /api/user/sessions/:sid`、`POST /api/user/sessions/revoke-others` |
| 控制台 PAT | `GET/POST/DELETE /api/user/token`；GET 也是旧版生成接口，不能漏掉 |
| Passkey 设置 | `POST /api/user/passkey/register/begin`、`register/finish`；`DELETE /api/user/passkey` |
| MFA 设置 | `POST /api/user/2fa/setup`、`enable`、`disable`、`backup_codes` |
| 邮箱绑定 | `POST /api/oauth/email/bind/start`、`bind/resend`、`bind` |
| 微信绑定 | `POST /api/oauth/wechat/bind` |
| OAuth 绑定 | `POST /api/oauth/state` 的 `intent=bind`；`GET /api/oauth/:provider` 对已经存在的绑定流程再校验角色，不能拿旧 flow 绕过新限制 |
| 自助解绑 | `DELETE /api/user/oauth/bindings/:provider_id` |
| 隐私 | `PUT /api/user/setting` 中实际改变 `record_ip_log` 的请求 |

隐私与通知设置共用接口，**不封整个 `/setting`**：未传/null 的隐私值保留原值；回传相同隐私值允许，兼容现有通知页合并保存；普通用户改变该值403，管理员仍可修改。JSON 大小写兼容不构成绕过。其他非本次范围的资料、语言、通知设置继续由原处理器负责。

旧 Telegram widget login/bind 路径在固定上游已统一返回410 `TELEGRAM_LEGACY_AUTH_REMOVED`，无实际绑定写入能力；本次不恢复，也不把它们误报为新增403。Telegram 的有效 OAuth 绑定走上述统一 `intent=bind` 分支。

### 明确保留

- `GET/PUT /api/user/self`：账户读取、改密/首次设密，以及原生非安全资料偏好更新仍可用；没有粗暴封整条 `/self`。
- `/api/verify/methods`、`POST /api/verify`、`/api/user/passkey/verify/*`：改密等操作的既有安全证明流程保留。
- 密码登录、`/api/user/login/2fa`、`login/verify`、`login/passkey/*`、`passkey/login/*`，以及 OAuth login/verify intent 保留。
- 找回密码 `/api/reset_password`、`POST /api/user/reset`，`auth/refresh`、`auth/logout` 保留。
- 状态读取、管理员按用户 ID 的重置/绑定/账户管理接口保留原权限；没有代替上游重置认证因子。
- **销售给客户的 API Key 是 `/api/token` 体系，与 `/api/user/token` 的控制台 PAT 不同。** 本次不扩大到客户 Key、钱包、账本、充值、模型权限等接口。

### 自删禁令

现有 Nginx 规范化 URI 的 `DELETE /api/user/self` 403规则原样保留，错误码 `SELF_ACCOUNT_DELETION_DISABLED`。新 Go 路由另加相同禁令兜底（普通用户和管理员自删均拒绝），管理员按 ID 管理账户不受此兜底影响。后端端口仍不得对客户直接开放；不能因为新增兜底就撤销入口限制。

## 3. 验证证据及边界

证据根目录：`evidence/account-security-restrictions/`。测试全部使用临时容器、临时数据库和隔离账户；没有打开/复制/修改生产数据库，没有真实模型/支付/GPU 调用。测试随机密码、Cookie、JWT、MFA secret/恢复码仅用于内存请求；Docker access logging 禁用，不截图认证表单或秘密。

| 验证 | 结果/证据 |
|---|---|
| 前端安全页及认证回归 | 12个测试文件、88项通过；`frontend-tests.log`。包含普通用户只挂载密码、伪造前端 admin store 不改变服务端 profile 决定、管理员保留卡片、密码键盘操作及加载失败重试 |
| 类型检查/生产构建 | `console/build.py` 内 `tsgo -b` + rsbuild，通过；`frontend-build.log`。静态产物仅在 `.console-build/web/dist` |
| Go 构建与回归 | Dockerfile 执行限流中间件、`TestModelPort*` 和选定上游密码/登录挑战/Passkey 测试，通过；`backend-build.log`。策略覆盖真实 UserAuth 的 session/PAT、普通/管理员/root、隐私缺省保留、既有 OAuth bind flow 拒绝、自删兜底 |
| 真实编译版浏览器 | 普通用户390/1440宽度仅密码卡片，刷新后仍正确，无横向溢出；`http-browser/user-security-390.png`、`user-security-1440.png` |
| 原生改密及退出 | 真实浏览器表单改密成功；旧密码和其他会话 token/refresh 失效；当前会话可刷新；个人菜单退出实际调用 logout 后无法再 refresh；`http-browser/results.json` |
| HTTP越权 | 17个固定写入/旧生成接口403，另测4类OAuth bind intent与隐私改变403；伪造header/body/query角色或篡改JWT不越权。原生管理员列表对普通用户仍403 |
| 管理员不误伤 | role=10真实管理员保留安全卡片，实际保存隐私、完成MFA注册/启用；原受限路由均未被新策略误封；root可创建管理测试用户 |
| 已有MFA客户 | 仅fixture中由管理员完成MFA后用原生root管理降为普通角色，认证因子保留；再次密码登录必须挑战，恢复码挑战实际完成；随后自助停用403且MFA仍启用 |
| 既有Passkey/挑战 | Go上游fixture执行真实签名验证、TOTP/恢复码、挑战重放与跨会话拒绝等测试；不是简单把挑战mock成成功。HTTP层另外验证登录/验证路由没有误挂新策略 |
| 自删403 | 临时真实ingress拒绝客户自删及尾斜杠/重复斜杠/编码/query变体；Go测试同时验证后端自删兜底 |
| refresh/logout限流 | 单独临时后端使用默认20/1200登录限额，25次匿名恢复、6次账户切换、31次认证恢复通过；登录触发429后仍可刷新/退出；`session-limits/results.json` |

**未实测/不作承诺：** 本次未连外部邮箱完成真实找回邮件，也未连 GitHub/OIDC/Telegram/微信供应商完成网络 OAuth 往返；找回及部分认证路由的HTTP检查只证明原handler可达并拒绝无效输入，不等于恢复成功。Passkey完整签名验证为Go测试fixture，不是真实手机/硬件Passkey验收。没有声称整个上游全部测试集或全平台ASVS合规通过；此前上游独立Passkey组件测试的QueryClientProvider问题不在本任务范围。

专项HTTP测试为避免多视口共用IP耗尽限额，只在临时后端设 `CRITICAL_RATE_LIMIT=200`；默认生产限流的正确性由独立 `auth_session_limits.py` 证明，生产配置未改。

## 4. 源文件与候选产物

- `console/overrides/src/features/security/index.tsx`、对应 `__tests__/page.test.tsx`：按服务端profile角色选择页面。
- `backend/account-security.patch`：精准路由挂载、OAuth bind 分支、隐私字段保留/限制；`auth-session-limits.patch` 原样保留并先应用。
- `backend/overrides/middleware/account_security_policy.go`：角色限制和自删拒绝；`backend/overrides/controller/account_security_policy_test.go`：专项Go测试。
- `backend/build.py`、`backend/Dockerfile`、`console/build.py`：构建/回归、独立候选输出与源码包；README和本说明为维护入口。
- `tests/account_security_restrictions.py`：独立HTTP/浏览器验收，自动销毁仅本次创建的临时容器/网络；复用既有测试工具，不部署。
- 前端候选：`.console-build/web/dist/`（含 `build-manifest.json`）。后端候选：本地镜像 `modelport-new-api:account-security-v1`，准确镜像ID及前端清单哈希以 `backend-dist/account-security-v1/build-manifest.json` 为准；源码包在同目录。

复验：

```sh
python3 console/build.py --prepare-only
(cd .console-build/web && npm exec --yes --package=bun@1.4.2 -- bun install --frozen-lockfile)
python3 console/build.py
python3 backend/build.py --work-dir .backend-security-next
python3 tests/account_security_restrictions.py
python3 tests/auth_session_limits.py --api-image modelport-new-api:account-security-v1 --output evidence/account-security-restrictions/session-limits
```

`--work-dir` 必须使用新的项目内专用目录，不覆盖现有构建树。前端覆盖层复制和构建不等于部署，严禁直接把当前挂载的 `console-dist/` 当测试输出。

## 5. 当前部署状态与后续约束

**已上线该限制版本。** `compose.yaml` 仅切换后端镜像，API优雅重建；前端及对应源码包同步到 `console-dist/`，旧哈希资源保留。当前后端清单/源码包同步到 `backend-dist/` 根目录，原候选子目录保留。Nginx/H5内容未改，ingress原容器仅reload。未修改公网/系统/OpenClaw/防火墙，未操作手机体验目录或其秘密。

上线前完成在线SQLite完整性备份及旧应用备份，路径 `backups/account-security-20260921-142325/`（含敏感信息，不上传）。上线前后用户/渠道/客户Key/日志数量均为3/1/1/1，原用户及数据挂载保留；未清理或修改认证配置。线上238个资源经HTTP逐个匹配候选哈希，自删路径变体继续403，25次匿名刷新均401。当前镜像与已发布前端的隔离角色/改密回归见 `evidence/account-security-deployed-artifacts/results.json`。

浏览器可能因后端重启需要重新登录。后续回滚不得解除自删禁令或削弱已有MFA/Passkey验证；不能倒灌备份覆盖新增业务数据。原候选证据保留历史状态，线上状态以新release证据为准。GitHub既有 `v2026.09.21.1` 离线包未被本次原站发布更新。

本次没有需要额外业务决定才能完成的阻塞。限制是平台对普通用户自助设置的政策，不代表新增了管理员代客户注册硬件Passkey等上游原本没有的功能。
