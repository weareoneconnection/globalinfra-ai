# GlobalInfra AI V6 证据协议

## 证据状态

- `VERIFIED_PASSED`：签名有效、数据集摘要一致、部署 commit 一致、CI 套件实际报告通过。
- `VERIFIED_FAILED`：证据包真实且与版本匹配，但至少一个门禁未通过。
- `UNVERIFIED`：缺签名、缺密钥、commit 不一致、工作区脏、数据集被改动或套件输出不完整。
- `NOT_RUN`：真实盲测或批准模型配置尚未提供。它不是失败，也绝不能显示成通过。

## 生成过程

```bash
python scripts/generate_release_evidence.py \
  --require-signature \
  --raw-dir /tmp/globalinfra-evidence-raw \
  --junit /tmp/globalinfra-junit.xml \
  --output services/api/evidence/release-evidence.json
```

CI 从 secret manager 注入 `EVIDENCE_SIGNING_PRIVATE_KEY`（Ed25519 PKCS8 PEM）并签名；运行中的 API **只持有** `EVIDENCE_VERIFICATION_PUBLIC_KEY`。私钥不得进入部署环境、容器镜像或浏览器变量。`--require-signature` 会在 Ed25519 私钥与有效兼容密钥均缺失时让发布任务失败；仅为历史兼容，也可显式使用不少于 32 字符的 HMAC `EVIDENCE_SIGNING_KEY`，但生产 API 必须同时设置 `EVIDENCE_ALLOW_LEGACY_HMAC=true`。产物包括三套 runner 原始 JSON、JUnit、release evidence 和模型对照协议输出。

三类签名材料必须分域且独立轮换：`COMPETITION_SIGNING_SECRET` 仅签发评委沙箱角色票据，`AUDIT_SIGNING_KEY` 仅签署审批/执行/核验/关闭回执，发布证据则由 CI Ed25519 私钥签名。任两者不得复用。审计回执同时持久化 `AUDIT_SIGNING_KEY_ID`；轮换时将旧密钥以验证专用形式加入 `AUDIT_VERIFICATION_KEYS` JSON key ring，确保历史链仍可按 key ID 验证，而旧密钥不再参与签名。

部署流水线必须下载 CI artifact，将 `release-evidence.json` 以只读方式挂载到 `RELEASE_EVIDENCE_PATH`，并设置与 artifact 源 commit 一致的 `GIT_COMMIT_SHA`/`RAILWAY_GIT_COMMIT_SHA`。只上传 GitHub artifact 而未挂载到运行服务时，API 会按设计返回 `RELEASE_EVIDENCE_MISSING`。API 通过 `/competition/evaluation-artifacts/latest` 验签；`/competition/evidence-bundle` 仅在签名、commit、数据集与结构全部验证后提供原始 envelope，失败时只返回原因而不回显挂载内容。

## 真实模型对照

`evals/run_model_comparison.py` 只接受获授权盲测集。最低字段为案例 ID、输入、期望风险、期望行动、期望证据及是否应拒答。四组固定为：

1. rules；
2. raw LLM；
3. LLM + RAG；
4. LLM + RAG + 国家包 + 引用校验 + 双人审批 + 独立核验。

每例至少运行三次，报告均值、置信区间、P50/P95、成本和失败分布。若 `MODEL_EVAL_*`、数据授权确认或至少 50 条盲测样本缺失，runner 返回 `NOT_RUN`。

## 禁止口径

- 不得把固定合成回归评测称为真实项目准确率。
- 不得用数据集行数推导“全部通过”。
- 不得手填测试数量、CI run ID 或固定核验回执 ID。
- 不得在签名无效、commit 不匹配或外部验证未完成时使用“已验证”“冠军指标”等字样。
