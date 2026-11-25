# 决赛快速上线模式

`COMPETITION_FAST_LAUNCH=true` 是仅供决赛演示期使用、可回滚的临时部署档位。它允许生产命名环境在暂未接入企业 OIDC、Redis 审计出箱、对象存储、外部签名密钥和 CI 发布证据时启动，但不会把这些缺项伪装成生产就绪。

## 不可放宽的边界

- 必须使用受管 Postgres，禁止 SQLite。
- `COMPETITION_V6_ENABLED=true`、`SANDBOX_MODE=true`。
- `SOD_ENFORCED=true`，审批、执行、核验、关闭角色仍分离。
- `AUDIT_MUTATIONS=true`，数据库审计仍开启。
- `EVIDENCE_BUNDLE_REQUIRED=false`；缺少发布证据时必须显示 `UNVERIFIED`，不得伪造通过。
- 图纸生成物继续保持 `AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION`，不能自动发布到正式 Twin。
- API 仅通过 Web BFF 的 Railway 私网访问，不给 API 服务添加公网域名。

## 暂时放宽的配置

- 企业 OIDC 与正式租户目录。
- Redis 审计出箱。
- 对象存储。
- 持久化的竞赛票据、审计签名密钥。
- Ed25519 发布证据与只读挂载包。

`/readyz` 在此模式返回 HTTP 200，同时明确输出 `readiness_class=DEGRADED_COMPETITION`、`release=NOT_READY` 和 `temporary_exceptions`。`/platform/production-readiness` 继续保持 `NOT_READY`。

## Railway 临时变量

```text
COMPETITION_FAST_LAUNCH=true
AUTH_MODE=disabled
REQUIRE_API_KEY=false
EVIDENCE_BUNDLE_REQUIRED=false
COMPETITION_V6_ENABLED=true
SANDBOX_MODE=true
SOD_ENFORCED=true
AUDIT_MUTATIONS=true
DEFAULT_ORGANIZATION_ID=globalinfra-demo
DEPLOYMENT_PROFILE=competition_fast_launch
```

Web 服务设置 `API_AUTH_MODE=disabled` 和 `DEPLOYMENT_PROFILE=competition_fast_launch`；生产 API 保持私网访问。

## 决赛后恢复严格门禁

1. 接入企业 OIDC、正式租户和项目授权。
2. 配置对象存储、持久 Redis 审计出箱与区域策略。
3. 将竞赛票据、审计签名与发布证据分别接入独立密钥域。
4. 挂载与部署 commit 绑定的只读 Ed25519 发布证据。
5. 设置 `COMPETITION_FAST_LAUNCH=false`、`EVIDENCE_BUNDLE_REQUIRED=true`。
6. 只有 `/platform/production-readiness` 返回 `READY` 后，才移除“决赛演示”标识并接入真实项目数据。
