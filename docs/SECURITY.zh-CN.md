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

- **三态身份边界**（`services/api/app/security.py`）：`disabled` 保留公开演示，`api_key` 提供抗时序侧信道的试点服务边界，`oidc` 通过 JWKS 验证签发方签名的 JWT。OIDC 声明会标准化为组织、角色和项目范围；变更接口执行 RBAC，审计平面记录操作者、请求与结果。
- **HTTP 与接入边界控制：** 显式 `CORS_ORIGINS` 白名单、浏览器安全响应头、文本请求长度限制、可配置上传大小上限、PDF/DOCX 文件签名校验以及二进制 TXT 拒绝。恶意软件扫描与 DLP 仍属于生产待办。
- **依赖安全基线：** Next.js 固定到本项目使用的最新已修复 15.x 版本，并锁定已修复的 PostCSS/source-map 间接依赖，已通过 `npm audit` 验证。
- Kubernetes 清单（`infra/kubernetes/`）已补充存活/就绪探针、资源请求/限制、`HorizontalPodAutoscaler`、说明所需密钥的 `api-secret.example.yaml`，以及带 TLS 的 `Ingress` 示例——这些都不能替代下面清单里的事项，但补上了"只有 Deployment"和"真正能运维起来的集群部署"之间的落差。
- 新增的 Terraform 起始代码（`infra/terraform/`）会创建一个私有 VPC、加密的 RDS PostgreSQL、加密的 ElastiCache Redis，以及一个启用 KMS 加密的 S3 桶，作为可供评审的 AWS 参考实现（并非生产认证基线）。

## 生产环境待办事项

- 启用客户身份租户、条件访问和 MFA，并验证最终声明映射及角色分配治理流程。
- RBAC + ABAC
- 行级租户/项目安全隔离
- KMS 支持的密钥加密
- 带签名的审计日志链
- 上传文件恶意软件扫描
- 数据防泄漏（DLP）与敏感数据分类
- 提示词注入（prompt-injection）测试套件
- CSP / HSTS 与完整的 API 速率限制（已启用防嵌入、内容类型、Referrer 与 Permissions 等基础响应头）
- SIEM 集成
- 备份/恢复演练
