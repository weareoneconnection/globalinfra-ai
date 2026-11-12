# GlobalInfra AI V6 生产就绪与 P0–P2 验收

V6 的发布原则是“配置不是证据，演示不是生产，目标值不是结果”。系统只在证据可追溯时显示 `VERIFIED_PASSED`；缺少签名、代码版本不一致、数据集被改动或 CI 产物缺失时统一显示 `UNVERIFIED`。

## P0：冠军演示可信性

已实现的代码门禁：

- 黄金案例统一为马来西亚轨道项目 V-12 高架桥 P47 桥墩高处作业通知。
- 原 `/competition/golden-thread/run` 已退役并返回 `410 LEGACY_AUTORUN_REMOVED`。
- `/competition/sessions` 为每位评委创建独立合成案例、TTL 和角色绑定 HMAC 票据；票据不能跨会话使用。
- 项目经理、HSE 经理、执行人、核验人和关闭人必须是五个不同主体；关闭人也不得复用任一审批人身份。
- 请求体中的 `executor`、`verifier` 不再决定 actor；回执只记录认证 Principal 或沙箱签名票据中的主体。
- 审批、执行、核验和关闭均持久化摘要及签名；输入、证据、回执字段或产物被修改后，核验或关闭失败。
- 三套确定性评测由 CI 统一生成 release evidence，包含数据集 SHA-256、代码 commit、模型配置、测试报告和签名。
- 规则、raw LLM、RAG、完整治理四组对照使用 fail-closed runner；盲测数据或批准的模型配置不存在时显示 `NOT_RUN`。

验收命令：

```bash
cd services/api
.venv/bin/python -m pytest tests/test_competition.py tests/test_evaluation_artifacts.py -q
```

## P1：试点控制面

- Project 和 Case 均持久化 `organization_id`；项目、工单、审批、行动、产物及回执按组织和项目范围过滤。
- P6 连接器执行 `globalinfra.p6.activity.v1` 规范校验，当前准确状态为 `SANDBOX_CONFIGURED` / `SANDBOX_VALIDATED`，不会冒充已建立厂商在线会话。
- Webhook 从部署根密钥按 connector ID 派生 HMAC 密钥；某一连接器的派生密钥不能跨连接器重放。部署根密钥一旦泄漏仍必须按全量连接器事件处理并立即轮换。
- 现场媒体的 SHA-256 内容去重与组织/项目授权分表保存；相同文件可被多个合法项目独立授权，旧的无项目媒体不能被“先知道哈希的人”认领。
- IntakeSubmission、SourceDocument 和 FieldMedia 均携带组织/项目边界；OCR worker 与后续文档能力不能依赖全局自增 ID 读取。
- 国家包包含来源摘要、复核人和失效日期。种子包状态为 `REVIEWED_DEMO` 且 release gate 为 `CLOSED`；只有具名 OIDC 人工复核且未过期才能打开。
- 数据库迁移 `0001→0016` 已通过 SQLite 与本地容器化 PostgreSQL 的全新升级链及 schema drift 检查；真实托管 PostgreSQL 的升级、回滚和恢复演练仍属于外部生产验收。

## P2：生产化骨架

生产环境启动校验要求：

- 非 SQLite 数据库，以及非本机的耐久 Redis 审计 outbox；
- OIDC 与 API 服务凭证；
- SOD 强制开启；
- 对象存储、耐久队列、数据驻留区域已配置；
- 至少 32 字符且彼此分离的 API、沙箱票据与治理回执密钥；运行服务仅持有发布证据 Ed25519 公钥，私钥留在 CI/KMS；
- 治理回执保存版本化 key ID，历史密钥仅通过 `AUDIT_VERIFICATION_KEYS` 验签，不再签发新回执；
- CI 生成的只读 `release-evidence.json` 已挂载到 `RELEASE_EVIDENCE_PATH`，部署 commit 与证据源 commit 一致；
- 备份保留期、RPO、RTO 与国家包最长复核周期已声明。

Web 的 `/healthz` 只证明 Next.js 进程可响应；部署 readiness 使用
`/readyz`，会在认证模式不受支持或 OIDC/加密会话配置缺失时返回 503。
该探针不访问身份提供方或 API，因此真实登录、授权与依赖连通性仍须在
部署后验收。

`GET /platform/production-readiness` 会实际验签 release evidence，并核对部署 commit、三套当前数据集摘要、API 测试、Web 构建、迁移、全栈烟测四个 CI gate 及三套评测结果；任何缺失或失配均为 `NOT_READY`。审计主写入失败会产生结构化告警、失败指标并写入 Redis Stream 持久 outbox，且 readiness 持续降级，直到主审计存储恢复。即便接口为 `READY`，正式生产声明仍必须附：

1. 数据库时间点恢复演练记录；
2. 对象存储版本与保留策略截图或 API 回执；
3. 队列重试、幂等和死信演练；
4. 至少 7 天的可用性、P95 延迟和错误率；
5. 数据驻留与跨境处理批准记录。

ROI 使用 `/pilot/roi-measurements` 记录配对基线。记录人与核验人必须不同；只有 `VERIFIED` 测量能进入 `/pilot/roi-summary` 的可声明结果。系统不计算无法证明的“避免事故价值”。

## 尚需外部输入

以下事项不能由代码替代，未完成前不得写成既有成绩：

- 50–200 条获授权脱敏盲测案例；
- 三名以上工程、HSE、合同专家双人标注与分歧裁决；
- 一个带真实凭证的 P6/CDE 沙箱连接；
- 恢复演练、SLO 观测和数据驻留批准；
- 真实影子试点及人工基线；
- 最终视频、专家签字、报名编号与提交回执。
- GitHub `release-signing` Environment 的分支/审批保护，以及签名私钥仅该环境可读的配置证据。
