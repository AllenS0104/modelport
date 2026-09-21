# ModelPort 账户界面

这是固定 New API 版本之上的**前端源码覆盖层**，不是第二套账户或计费系统。`upstream/` 保持原样；`overrides/` 覆盖布局、默认配色、品牌组合、公共导航、跨静态应用的登录返回，以及平台禁用自助删号的界面策略。现有登录表单、MFA、Passkey、邮箱/人机/条款验证、Key/钱包/账单和管理员权限实现继续复用原项目。

## 构建

在项目根目录保留完整的 `upstream` Git 源码，HEAD 必须为 `385d2dfd10d821b25c8a6766bd16eea248cb1652`，且工作树干净。Linux 主机需要 Python 3.12+、Node/npm，使用 Bun 1.4.2 和原始 `bun.lock`：

```sh
python3 console/build.py --prepare-only
cd .console-build/web
npm exec --yes --package=bun@1.4.2 -- bun install --frozen-lockfile
cd ../..
python3 console/build.py
```

产物在 `.console-build/web/dist`，构建本身**不会替换线上文件或启动服务**。通过隔离验收后，将完整产物部署为项目 `console-dist/`；Nginx 容器以只读方式挂载到 `/srv/modelport-console`。必须同时发布 H5、Nginx、Compose 和前端产物；首次增加挂载需要仅重建 ingress，New API 服务无需重启。

下载的源码包保留 `upstream/` 完整源码快照但不包含 Git 数据库；执行上述固定提交校验前，可从官方 `https://github.com/QuantumNous/new-api` 获取该提交的 Git 工作树，核对包内快照，并在同一项目根目录保留 `console/`。依赖恢复使用锁文件，不能随意升级包或把另一上游版本直接套入覆盖层。

`routes.conf` 从真实前端路由及兼容旧路径生成，只接管这些界面的 GET/HEAD；`/api/`、`/v1/`、`/pg/` 等仍使用原代理路径。脚本/CSS位于同源 `/console-assets/`。未知 API、SSE、Host 限制和旧 `/preview/` 不改变。没有 iframe、DOM 注入、代理改写响应、凭据转交或跨域绕过。

`build-manifest.json` 记录固定上游提交及所有资源哈希。`modelport-source.tar.gz` 提供完整固定上游源码、覆盖层、锁文件和本说明，可从网站页脚下载；原项目标识、版权、许可证及第三方构建 notice 保留。源代码包不包含客户数据、运行凭据、日志或备份。

## 设计与行为

### 自助删号策略

平台不开放用户自助删除账户。安全页覆盖层移除原生 `Account Actions` 删除卡片，仍保留修改密码、会话、MFA、Passkey、绑定与隐私设置。`nginx.conf` 同时在服务端入口拒绝 `DELETE /api/user/self`，返回 HTTP 403 和稳定错误码 `SELF_ACCOUNT_DELETION_DISABLED`；并非只隐藏按钮。匹配规范化 URI，覆盖编码、重复斜杠、尾斜杠和查询参数；旧页面及直接 HTTP 请求也不能通过本站入口自删。

账户查询/修改、撤销会话与 Key，以及原生管理员按权限管理账户的接口不受此规则影响。需关闭账户时由平台管理员处理，不能把自助删除当成钱包或账本的清理工具。

**部署约束：New API 的原生自删处理器仍在官方镜像中，必须保持后端端口不对客户开放，所有客户流量经过受控 ingress。** 将来新增域名、负载均衡或另一入口时必须保留这一策略，不能直接暴露后端。域名准备器复制本规则，回归脚本检查其保留。回滚前端时也不得顺带撤销已经生效的删号禁令。

修改依据 OWASP [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) 与 [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)：在服务端强制策略，不依赖前端隐藏；保留其他敏感操作的原生身份验证，不记录凭据。不声称因此完成整个平台的 ASVS 合规审计。

- 官网和账户页沿用“模港 ModelPort”、MP标记、浅灰底、深蓝主按钮及绿色强调色；原生明确选择的其他主题和暗色仍保留。
- 注册、登录、找回密码等复用共同 `AuthLayout`。管理员首次初始化显示相同产品标识，保留“初始化 New API”原始技术说明。
- Key、钱包、消费、安全与管理页沿用原组件，只统一上方标识、配色和返回官网/聊天/教程的导航。业务页密集表格的布局不强行变成官网卡片。
- 从 H5 登录后，经原有会话验证和 MFA（如启用）自动返回 `/h5/#chat`，新文档通过同源 HttpOnly refresh Cookie 恢复会话。令牌不放进 URL 或新增浏览器存储。
- 未指定返回地址的普通客户登录默认进入聊天；管理员默认仍进管理控制台。已有安全重定向校验保留，外站目标不会被接纳。
- 品牌仍是工作名。改名时同步 H5 的 `body[data-brand]` 与 `src/components/platform-brand.tsx`，并重新构建；不通过客户数据库中的系统名去冒充另一套账户。

复用的是既有 `AuthLayout`、`SystemBrand`、`PublicHeader`、`TopNav`、主题变量和表单组件。新组件 `PlatformBrand`/`PlatformAttribution` 只承载统一标识与来源，不重复实现表单、确认弹窗或权限逻辑。H5 与 React 是两个同源前端入口，因此这些入口之间使用完整文档导航，而不是让 React 路由渲染不存在的 `/h5/` 页面。

认证导航修改参考 OWASP Authentication / Session Management Cheat Sheets，保持服务端权限、验证挑战、会话旋转与撤销、不泄露凭据的既有机制。本轮不声称整体通过 ASVS 合规审核；公网 TLS、上游授权、计费和运营上线仍需单独验收。

## 验证与回滚

- `bun run typecheck`、修改文件的 oxlint / oxfmt、`bun run test src/features/auth`。
- 项目 `tests/chat_integration.py`：临时原生后端、真实注册登录与返回、客户/管理员界面、聊天/API同账本、退款及越权拒绝；不连接付费 AI。
- `tests/console_interface.py`：手机/桌面账户页、Key、钱包、消费、安全、价目和管理员渠道/审计界面。
- 多视口验收在单一IP上反复重载；仅临时测试后端设 `CRITICAL_RATE_LIMIT=200`，生产限流不改。默认20次/20分钟的关键请求限流曾真实返回429，不将其误判成Cookie互通失败，也不绕过生产限流。
- 生产只读预览与 CSP 校验仍由 `tests/features_registration_model.py` 等执行；未初始化不代表这些功能已对真实客户开通。

回滚界面时恢复前一版 `console-dist/` 入口及静态资源，**保留当前 Nginx 自助删号拒绝规则**，不能从禁令生效前的备份整体覆盖 Nginx。一般无需调整 Compose；若确需变更挂载，仅重建 ingress，并再次确认后端未直接暴露。不要回滚数据库、重启 OpenClaw 或退役飞书桥。后续更新应保留前一版本静态哈希资源直至旧页面退出，避免正在打开的控制台缺少懒加载资源。
