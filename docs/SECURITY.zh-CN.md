> **Language / 语言**: [English](SECURITY.md) · 简体中文

# 安全基线

## 原则

- 将上传的文档视为不可信数据，绝不能当作系统指令。
- 对工具调用实施白名单与最小权限原则。
- 按授权策略隔离不同项目/租户的访问权限。
- 对合同类、监管类、付款类、进度承诺类、安全停工类以及对外函件类行动，强制要求人工审批。
- 保留证据的来源可追溯性与审计上下文。
- 绝不将密钥放入提示词（prompt）、日志或演示文件中。

## 目前已落地的能力

- **试点阶段 API Key 网关**（`services/api/app/security.py`，默认通过 `REQUIRE_API_KEY=false` 关闭）：对除 `/health` 外的每个请求校验一个共享密钥，只需在对应环境设置 `REQUIRE_API_KEY=true` 与 `API_KEY=...` 即可启用，无需改代码。这只是试点阶段的网络边界兜底方案，**不能替代**下方的 SSO/OIDC 事项——它没有按用户区分的身份、角色或审计轨迹。
- Kubernetes 清单（`infra/kubernetes/`）已补充存活/就绪探针、资源请求/限制、`HorizontalPodAutoscaler`、说明所需密钥的 `api-secret.example.yaml`，以及带 TLS 的 `Ingress` 示例——这些都不能替代下面清单里的事项，但补上了"只有 Deployment"和"真正能运维起来的集群部署"之间的落差。
- 新增的 Terraform 起始代码（`infra/terraform/`）会创建一个私有 VPC、加密的 RDS PostgreSQL、加密的 ElastiCache Redis，以及一个启用 KMS 加密的 S3 桶，作为可供评审的 AWS 参考实现（并非生产认证基线）。

## 生产环境待办事项

- SSO / OIDC / SAML + 多因素认证（MFA）（上面的 API Key 网关只是过渡性的网络边界控制，不是身份系统）
- RBAC + ABAC
- 行级租户/项目安全隔离
- KMS 支持的密钥加密
- 带签名的审计日志链
- 上传文件恶意软件扫描
- 数据防泄漏（DLP）与敏感数据分类
- 提示词注入（prompt-injection）测试套件
- CSP / HSTS 与完整的 API 速率限制
- SIEM 集成
- 备份/恢复演练
