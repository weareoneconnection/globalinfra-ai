# V6_EVIDENCE

本目录是 V6 冠军版外部证据入口，不存放客户原文、密钥或个人信息。

建议最终结构：

```text
00_RELEASE/          签名 manifest、commit、SBOM、CI 链接
01_AUTHORIZATION/    数据授权、处理登记、脱敏与保留记录
02_DATASET/          数据卡、切分方案、封存哈希
03_ANNOTATION/       标注指南、一致性、裁决报告
04_EVALUATION/       四组原始预测、指标、置信区间、错误分析
05_PILOT/            人工基线、影子试点、ROI 配对测量
06_GOVERNANCE/       双人审批、越权阻断、红队与受限路由
07_REPRODUCIBILITY/  容器摘要、三台干净环境复现日志
08_EXPERT_REVIEW/    专家角色、签字、限制与例外
09_SUBMISSION/       报告、视频、报名和提交回执
```

当前仓库只提供结构、代码门禁和生成器。真实数据授权、盲测输出、专家签字、试点结果与提交回执尚未获得，因此不得创建占位“通过”文件。

## 当前证据状态（2026-11-12）

- 当前工作树的 P0–P2 API 回归、三套固定合成回归 runner、SQLite 全新迁移链，以及使用 `.env.example`、独立项目名和新卷的容器化 PostgreSQL/Redis/API/Web 全栈烟测已在本地通过；PostgreSQL 已验证 `0001→0016`、schema drift 和 `0016→0015→0016`。这里不抄写易失真的测试数量，最终数量只能从同一 commit 的 JUnit 与原始 runner JSON 读取。
- 真实模型对照 runner 按设计返回 `NOT_RUN`，原因为尚未提供获授权盲测集和批准的模型配置；这不是模型效果成绩。
- Web ESLint、TypeScript 静态编译、本地 Next.js 生产构建，以及 Railway 干净 Node 22 + `npm ci` Docker 构建均已通过；这仍不是受保护签名 CI 的发布证明。
- Web OIDC 登录发起、PKCE/state/nonce、RSA/JWKS ID Token 验签、加密 HTTP-only session、BFF 用户令牌转发、精确公开白名单与 `/healthz` 已通过本机 HTTPS 模拟 IdP 边界烟测；坏签名会失败且不签发 session。Web `/readyz` 的 demo/有效 OIDC/无效配置三态也已在本机验证，但不代表真实依赖连通。真实企业 IdP 的授权码交换、角色/项目声明和注销仍须部署联调。
- 应用提交 `1c1373d` 已推送到 `v6-competition-demo` 分支并部署至隔离的 Railway `competition-demo`。公网 Web/API `/readyz`、证据 API 及 Web BFF 七步合成沙箱闭环已在线验收；双人审批、执行、独立核验、关闭均成功，且未执行外部交付。
- 该环境刻意使用 `AUTH_MODE=disabled`、mock AI 和临时 SQLite，且未挂载签名 release envelope，因此只属于可运行竞赛演示，证据状态必须保持 `UNVERIFIED`，不能称为生产发布或生产就绪。

只有同一冻结 commit 生成且验签成功的 `release-evidence.json`、对应原始 JSON/JUnit、云端 CI 链接和部署在线核验结果，才能把发布状态提升为 `VERIFIED_PASSED`。

冻结发布前还必须在 GitHub 实际创建并保护 `release-signing`
Environment（限制分支/审批人，并确保 Ed25519 私钥只对该环境可读）；工作流中的
`environment:` 声明本身不是已完成证明。
