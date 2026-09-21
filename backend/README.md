# New API 会话限流补丁

固定上游 `385d2dfd10d821b25c8a6766bd16eea248cb1652`（QuantumNous/new-api v1.0.0-rc.37）。只替换刷新和退出两条路由的限流器，不改变认证、Cookie、密码、安全证明、权限、账本或数据库结构。

- 登录、注册、安全验证等仍使用原有 `CriticalRateLimit`，当前为每来源 IP 20 次 / 1200 秒；用户级敏感操作限制不变。
- `POST /api/user/auth/refresh` 和 `POST /api/user/auth/logout` 各自使用独立的每 IP 120 次 / 60 秒限额，互不挤占，也不消耗登录防刷额度。
- 会话限额持续生效，超限返回429及 `Retry-After`。不使用 Cookie 值、用户名或可伪造请求头作为绕过限流的依据。
- 本地 SSH 隧道仍可能把多个浏览器/账户视为同一来源；我们不伪造来源 IP，也不开放对任意代理头的信任。未来公网部署须单独配置并验证可信代理链。

## 构建和验收

项目根目录需要干净的固定 `upstream/`、已验收的 `console-dist/` 和 Docker：

```sh
python3 backend/build.py
python3 tests/auth_session_limits.py --api-image modelport-new-api:auth-session-limits-v1
python3 tests/chat_integration.py --api-image modelport-new-api:auth-session-limits-v1
```

构建在专用 `.backend-build/` 中展开上游快照并应用补丁，使用上游锁定的 Go 构建镜像。先执行限流回归与编译，再基于原官方镜像替换 `/new-api` 二进制。输出本地镜像 `modelport-new-api:auth-session-limits-v1`，以及 `backend-dist/build-manifest.json`、含原始上游和前后端覆盖层的 `backend-dist/modelport-source.tar.gz`。不上传镜像，不自动部署，不修改 `upstream/`。重复构建前须检查并仅清理自己上次创建的 `.backend-build/`。

发布前确认镜像 ID 与清单一致；备份配置、前端资源清单，并通过 SQLite 在线备份接口备份数据库。更新 H5 精确 CSP、对应源码包及资源清单后，再用 Compose 重建 API 服务并 reload ingress。当前没有配置稳定 SESSION_SECRET，重启可能需要重新登录，不承诺旧会话持续有效；不为恢复会话去提取进程内秘密。用户、客户 API Key、额度和账本不能因修复被重建或清空。

回滚恢复前一版镜像和配置，不覆盖期间新增业务数据，不解除现有自助删号禁令。对外仍只能通过 ingress，后端端口不得直接暴露。AGPLv3、原作者署名和对应源码下载要求继续适用；镜像内 `/licenses/modelport-backend` 同时提供维护补丁。

参照 OWASP Authentication / Session Management Cheat Sheets：不以放大或关闭登录防刷来解决会话恢复问题，不把浏览器提示 Cookie 当成身份验证，不改变会话旋转、撤销及敏感操作二次验证。
