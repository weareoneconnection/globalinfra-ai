> **Language / 语言**: [English](RELEASE_NOTES.md) · 简体中文

# GlobalInfra AI V1.0 发布说明

本次发布建立了一个独立的、可用于竞赛展示且可全球扩展的基础平台。

## 已实现

- 全局指挥中心
- 项目与工单领域模型
- 确定性多智能体演示运行时
- 证据链与核验关卡
- 人工审批工作流
- 知识网络演示
- 多语言 HSE 培训演示
- 马来西亚国家包，及其他区域包骨架
- 铁路领域包，及其他五个交通领域包骨架
- Docker Compose 部署
- Kubernetes 启动清单
- 模拟竞赛数据与评测冒烟测试框架
- 独立的知识产权边界文档
- 系统全链路中英文切换：前端自动识别浏览器语言、后端 API 双语数据返回、翻译模型集成点

## V1.1 工程加固新增项

- 真实的评测框架：`evals/run_eval.py` 现在会用一个确定性的、基于规则的分类器（`services/api/app/classify.py`，同时作为 `POST /cases/classify` 端点对外暴露）对 `evals/datasets/cases.jsonl` 跑断言，比对预测出的类型/风险等级与期望标签，而不只是检查数据集字段是否齐全。分类器出现回归会直接导致构建失败。
- `services/api/tests/`：新增 pytest 测试套件，覆盖 i18n 本地化、翻译离线短语表的兜底逻辑、分类器、新增的 API Key 网关，以及"`POST /cases/{id}/analyze` 是否幂等"的端到端校验。
- CI（`.github/workflows/ci.yml`）现在每次 push/PR 都会跑这套 pytest，并新增了一个 `docker-compose-smoke-test` job，用 `docker compose up --wait` 真正拉起整套服务再 curl 验证，填补了此前"Docker Compose 路径从未被 CI 验证"的空白。
- 新增试点阶段、默认关闭的共享密钥 API 网关（`services/api/app/security.py`，`REQUIRE_API_KEY` / `API_KEY`），可按环境开启且无需改代码。这只是过渡性的网络边界控制，不能替代下面仍待完成的企业级 SSO/OIDC。
- `infra/kubernetes/` 清单补充了存活/就绪探针、资源请求/限制、`HorizontalPodAutoscaler`、说明所需密钥的示例 `Secret`，以及示例 `Ingress`。
- `infra/terraform/` 现在是一套可运行（但刻意保持最小化、且仅覆盖 AWS）的起始代码——私有 VPC、加密的 RDS PostgreSQL、加密的 ElastiCache Redis、启用 KMS 加密的 S3——已通过 `terraform validate` 校验，替换掉了原来的纯文字清单。
- 修复了一处文档错误：Docker 快速启动章节原先写的是 8000 端口，而 `docker-compose.yml` 实际把 API 容器映射到了宿主机的 8001 端口。

## 有意延后实现

- 企业级 SSO / OIDC / SAML + 多因素认证（MFA），以及细粒度 ABAC（上面的试点阶段 API Key 网关只是网络边界层面的过渡方案，不是身份认证系统）
- 生产级对象存储与文档 OCR/解析流水线
- pgvector / OpenSearch / Neo4j 投影
- Temporal 长时间运行工作流服务
- 区域化 Kubernetes 控制面/数据面部署（清单已具备探针/HPA/Ingress，但真正的区域化上线仍待完成）
- 完整的离线优先现场 PWA 同步引擎
- BIM / GIS / IoT 集成

以上属于 V1.1+ 的加固/扩展项，并非当前演示工作流的隐藏依赖。
