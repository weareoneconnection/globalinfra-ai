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

## 当前证据状态（2026-11-25）

- 当前工作树的 P0–P2 API 回归、三套固定合成回归 runner、SQLite 全新迁移链，以及使用 `.env.example`、独立项目名和新卷的容器化 PostgreSQL/Redis/API/Web 全栈烟测已在本地通过；PostgreSQL 已验证 `0001→0016`、schema drift 和 `0016→0015→0016`。这里不抄写易失真的测试数量，最终数量只能从同一 commit 的 JUnit 与原始 runner JSON 读取。
- 真实模型对照 runner 按设计返回 `NOT_RUN`，原因为尚未提供获授权盲测集和批准的模型配置；这不是模型效果成绩。
- Web ESLint、TypeScript 静态编译、本地 Next.js 生产构建，以及 Railway 干净 Node 22 + `npm ci` Docker 构建均已通过；这仍不是受保护签名 CI 的发布证明。
- Web OIDC 登录发起、PKCE/state/nonce、RSA/JWKS ID Token 验签、加密 HTTP-only session、BFF 用户令牌转发、精确公开白名单与 `/healthz` 已通过本机 HTTPS 模拟 IdP 边界烟测；坏签名会失败且不签发 session。Web `/readyz` 的 demo/有效 OIDC/无效配置三态也已在本机验证，但不代表真实依赖连通。真实企业 IdP 的授权码交换、角色/项目声明和注销仍须部署联调。
- 应用提交 `4b121186bd066c252caafa2355c46d68e7a60f2e` 已通过受保护 CI：API、Web、迁移、全栈烟测、332 项 API 测试和 57 条三组固定合成评测全部通过。CI 生成 Ed25519 签名证据、镜像 provenance 与 digest-only manifest；演示 API 运行 `ghcr.io/weareoneconnection/globalinfra-api@sha256:3052e5399c07e6a6126151f9c46d1536053d30fe7ff8a4f0952f199f66fd123b`。
- 隔离的 Railway `competition-demo` 已在线验收 V6.1 Web/API、`/readyz`、证据 API、Web BFF 与九步 Jury 闭环；越权 403、篡改副本拒绝、双人审批、执行、独立核验、关闭均成功，外部交付保持 `false`。证据状态为 `VERIFIED_PASSED`，并绑定上述 commit、公钥和镜像 digest。
- 该环境仍刻意使用 `AUTH_MODE=disabled`、mock AI 和临时 SQLite，因此只属于具有签名发布证据的竞赛演示，不能称为生产发布或生产就绪；真实模型盲测仍按事实显示 `NOT_RUN`。

只有同一冻结 commit 生成且验签成功的 `release-evidence.json`、对应原始 JSON/JUnit、云端 CI 链接和部署在线核验结果，才能把发布状态提升为 `VERIFIED_PASSED`。

GitHub `release-signing` Environment 已限制为 `main`、配置发布审批人，并将 Ed25519
私钥限定为环境 secret；运行时仅接收公钥，临时私钥文件不会进入仓库、构建产物或
Railway。
