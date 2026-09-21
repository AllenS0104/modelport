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

`routes.conf` 从真实前端路由及兼容旧路径生成，只接管这些界面的 GET/HEAD；`/api/`和客户`/v1/`保留原生鉴权/转发。API-only版本禁用`/pg`，旧聊天、Playground和预览入口重定向；不提供网页聊天。脚本/CSS位于同源`/console-assets/`。没有iframe、DOM注入、凭据转交或跨域绕过。

`build-manifest.json` 记录固定上游提交及所有资源哈希。`modelport-source.tar.gz` 提供完整固定上游源码、覆盖层、锁文件和本说明，可从网站页脚下载；原项目标识、版权、许可证及第三方构建 notice 保留。源代码包不包含客户数据、运行凭据、日志或备份。

## 设计与行为

### 自助删号策略

平台不开放用户自助删除账户。安全页覆盖层移除原生`Account Actions`删除卡片。普通用户只挂载密码操作卡片；管理员仍保留会话、控制台访问令牌、MFA、Passkey、绑定与隐私设置。这不是新增客户端管理权，服务端独立复用已认证角色并强制策略。策略详见`../ACCOUNT-SECURITY-RESTRICTIONS.zh-CN.md`；当前发布是否已部署到某个环境，应核对该环境的运行镜像，不能仅凭源码判断。Nginx和Go后端都拒绝`DELETE /api/user/self`，返回403及`SELF_ACCOUNT_DELETION_DISABLED`，并非只隐藏按钮。旧页面及直接HTTP请求也不能通过本站入口自删。

账户查询/修改、撤销会话与 Key，以及原生管理员按权限管理账户的接口不受此规则影响。需关闭账户时由平台管理员处理，不能把自助删除当成钱包或账本的清理工具。

**部署约束：即使Go后端有拒绝中间件，也不能开放后端端口，所有客户流量仍须经过受控ingress。** 新增域名、负载均衡或另一入口时必须保留策略；回滚前端不得撤销已生效的禁令。

修改依据 OWASP [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) 与 [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)：在服务端强制策略，不依赖前端隐藏；保留其他敏感操作的原生身份验证，不记录凭据。不声称因此完成整个平台的 ASVS 合规审计。

- 官网和账户页沿用“模港 ModelPort”、MP标记、浅灰底、深蓝主按钮及绿色强调色；原生明确选择的其他主题和暗色仍保留。
- 注册、登录、找回密码等复用共同 `AuthLayout`。管理员首次初始化显示相同产品标识，保留“初始化 New API”原始技术说明。
- Key、钱包、消费与管理页沿用原组件。普通用户常规导航仅数据看板、概览、API密钥、使用日志、任务日志；审计仅管理员可见，聊天与Playground入口移除。默认简体中文，保留用户明确选择的语言。
- 经原有会话验证和MFA（如启用）后进入控制台；新文档通过同源HttpOnly refresh Cookie恢复会话，令牌不放进URL或新增浏览器存储。
- 未指定返回地址时默认进入`/dashboard/models`；保留安全重定向校验，外站目标不会被接纳，旧聊天地址不会恢复网页聊天。
- 品牌仍是工作名。改名时同步 H5 的 `body[data-brand]` 与 `src/components/platform-brand.tsx`，并重新构建；不通过客户数据库中的系统名去冒充另一套账户。

复用的是既有 `AuthLayout`、`SystemBrand`、`PublicHeader`、`TopNav`、主题变量和表单组件。新组件 `PlatformBrand`/`PlatformAttribution` 只承载统一标识与来源，不重复实现表单、确认弹窗或权限逻辑。H5 与 React 是两个同源前端入口，因此这些入口之间使用完整文档导航，而不是让 React 路由渲染不存在的 `/h5/` 页面。

认证导航修改参考 OWASP Authentication / Session Management Cheat Sheets，保持服务端权限、验证挑战、会话旋转与撤销、不泄露凭据的既有机制。本轮不声称整体通过 ASVS 合规审核；公网 TLS、上游授权、计费和运营上线仍需单独验收。

## 验证与回滚

- `bun run typecheck`、修改文件的 oxlint / oxfmt、`bun run test src/features/auth src/features/security/__tests__/page.test.tsx`。
- 新账户安全专项：`python3 tests/account_security_restrictions.py`，默认只挂载 `.console-build/web/dist` 到临时 ingress，绝不替换正在运行的 `console-dist/`。配套 Go 镜像按 `backend/README.md` 构建；发布必须单独授权并一起切换前后端，不能只藏按钮。
- 当前集成入口为`tests/api_sales.py`：一次性后端、中文导航、模型删除、账户/Key权限、实际计费和隔离SMTP。`--extended-scenarios --upstream-issues`增加业务边界与缺陷回归；不使用真实供应商。`tests/chat_integration.py`仅保留供共享测试工具复用及历史参考，不是当前网页聊天放行标准。
- `tests/console_interface.py`：手机/桌面账户页、Key、钱包、消费、安全、价目和管理员渠道/审计界面。
- 多视口验收在单一IP上反复重载；仅临时测试后端设 `CRITICAL_RATE_LIMIT=200`，生产限流不改。默认20次/20分钟的关键请求限流曾真实返回429，不将其误判成Cookie互通失败，也不绕过生产限流。
- 生产只读预览与 CSP 校验仍由 `tests/features_registration_model.py` 等执行；未初始化不代表这些功能已对真实客户开通。

回滚界面时恢复前一版 `console-dist/` 入口及静态资源，**保留当前 Nginx 自助删号拒绝规则**，不能从禁令生效前的备份整体覆盖 Nginx。一般无需调整 Compose；若确需变更挂载，仅重建 ingress，并再次确认后端未直接暴露。不要回滚数据库、重启 OpenClaw 或退役飞书桥。后续更新应保留前一版本静态哈希资源直至旧页面退出，避免正在打开的控制台缺少懒加载资源。
