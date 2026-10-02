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

## V1.2 真实多智能体推理升级

此前，`POST /cases/{id}/analyze` 其实是一段脚本：它只针对某一个写死的 `case_id` 分支，插入固定的英文结论文案和固定的耗时毫秒数，证据也是手工挑选的。`agents.py` 里的 20 个智能体目录只用于展示——其中列出的工具没有一个被真正调用过。本次发布用一套真实的流水线替换了这段脚本：

- `services/api/app/retrieval.py`：一个无需额外依赖的 TF-IDF 余弦相似度检索引擎，对 `KnowledgeDocument` 建立索引，并同时索引每份文档的中英文文本，因此任一语言的查询都能检索到另一语言撰写的证据，无需任何翻译调用。每一次排序结果都可以通过其相似度分数复现、审查。
- `services/api/app/workflow.py`（重写）：现在由 `Case.type` 决定 `agents.py` 目录中哪些专业智能体真正参与运行（见 `SPECIALISTS_BY_CASE_TYPE`）——HSE 类工单会调用 HSE / 合规 / 人力智能体，合同 / 技术接口类工单会调用合同 / 工程 / 接口智能体，以此类推。每个参与的智能体都会基于工单自身文本发起真实检索，只引用它真正找到的证据；当相关度不足以支撑结论时，会明确指出证据不足，而不是给出结论——这一规则适用于任何工单，而不只是过去那个被写死的示例。
- 证据置信度，以及核验智能体给出的引用、证据、一致性三项分数，都是根据本次运行实际产生的证据与结论计算得出，而非固定数字。
- 智能体运行耗时现在是检索与结论生成过程的真实墙钟耗时，而不是写死的常数。
- 当配置了真实的 OpenAI 兼容模型时（`llm_mode` 不为 `mock` 且设置了 `OPENAI_COMPAT_API_KEY`），每个专业智能体的结论都会由该模型生成，并基于同一批检索到的证据，再经同一模型翻译。默认的、无需联网的模式则会直接基于本身已是双语的知识库文档，同时生成两种语言的结论文本，因此离线 / CI 场景下依然保持完全确定性，且不再依赖一张预先无法穷举的固定短语表——`translations.py` 中被这套新逻辑取代的旧有逐工单固定短语已被清理。
- 新增测试：`tests/test_retrieval.py`（检索引擎本身）、`tests/test_workflow.py`（验证不同类型的工单确实会调用不同的智能体，且证据与分数均源自真实知识库）、`tests/test_workflow_llm_mode.py`（验证真实模型调用路径确实被执行，而不只是离线兜底逻辑）。

## 有意延后实现

- 企业级 SSO / OIDC / SAML + 多因素认证（MFA），以及细粒度 ABAC（上面的试点阶段 API Key 网关只是网络边界层面的过渡方案，不是身份认证系统）
- 生产级对象存储与文档 OCR/解析流水线
- pgvector / OpenSearch / Neo4j 投影
- Temporal 长时间运行工作流服务
- 区域化 Kubernetes 控制面/数据面部署（清单已具备探针/HPA/Ingress，但真正的区域化上线仍待完成）
- 完整的离线优先现场 PWA 同步引擎
- BIM / GIS / IoT 集成

以上属于 V1.1+ 的加固/扩展项，并非当前演示工作流的隐藏依赖。
