> **Language / 语言**: [English](README.md) · 简体中文

# GlobalInfra AI V4.3

**全球交通基础设施智能与可信执行平台**

GlobalInfra AI V4.3 是一个面向海外基础设施项目的运营级数字孪生与可信执行平台。它把完整项目生命周期和八大智能领域连接到实时几何、进度、成本、遥测与证据化决策，并将整条链路固化为可复现的参赛黄金主线、评测证据与六入口统一数据接入控制面。

> 范围说明：本仓库是一个全新的独立代码库。它不依赖、不导入、不调用、也不暴露 TheOne 或任何 TheOne 品牌的运行时。

## V1.1 中可运行的能力

- 智能助手对话入口（默认首页）
- 全局指挥中心仪表盘
- 具备生命周期感知能力的项目组合与项目工作空间
- 覆盖 24 个工程专业的八大智能领域
- 贯穿技术、交付、商务与资产记录的基础设施数字主线
- 工单智能工作流
- 动态专家团队组建与多智能体分析轨迹
- 有证据支撑的决策
- 审批中心
- 知识检索
- 劳动力能力资质与本地化培训能力
- 国家包（Country Packs）与领域包（Domain Packs）
- 业主函件工作流定义
- 独立核验记录
- 模拟演示数据集
- Web + API + PostgreSQL + Redis 的 Docker Compose 编排
- 评测框架与 CI 骨架
- **全链路中英文切换**：前端跟随浏览器语言自动识别（可手动覆盖），后端 API 按语言返回双语数据，并接入翻译模型用于动态生成内容的翻译

默认 AI 模式是**确定性演示模式**，因此系统无需购买模型额度即可运行。平台内置了一个与 OpenAI 协议兼容的模型网关，之后可以通过环境变量启用真实模型。

## 快速开始：Docker（推荐）

依赖：Docker Desktop。

```bash
cp .env.example .env
docker compose up --build
```

打开：

- Web：http://localhost:3000
- API 文档：http://localhost:8001/docs
- API 健康检查：http://localhost:8001/health

（`docker-compose.yml` 把 API 容器内部的 8000 端口映射到了宿主机的 8001 端口，因为 8000 在很多机器上已被占用；Web 容器通过 Docker 内部网络用 8000 端口访问 API，`API_INTERNAL_URL` 不受影响。）

### 使用本地 Ollama 模型运行

安装 Ollama 并拉取模型（例如 `qwen3:8b`），然后使用本地模型覆盖配置启动同一套服务。Ollama 不需要填写占位 API Key。

```bash
ollama pull qwen3:8b
docker compose -f docker-compose.yml -f docker-compose.local-llm.yml up --build
```

如需使用其他 OpenAI-compatible 本地网关，可在 `.env` 中覆盖 `LOCAL_LLM_MODEL` 或 `LOCAL_LLM_BASE_URL`。API 容器通过 `host.docker.internal` 访问宿主机；云端模式仍强制要求 `OPENAI_COMPAT_API_KEY`。

### 运行时模型路由

同一个运行中的 API 可按每次请求选择 `local`、`openai` 或 `auto`，不会修改进程级全局状态。`auto` 先使用 `LLM_PREFERRED_PROVIDER`，失败时可切换到另一个已配置提供方；设置 `LLM_CLOUD_FALLBACK_ENABLED=false` 可禁止从本地回退到云端。标记为 `restricted` 的数据始终只能在本地处理，即使显式请求 OpenAI，也会在发出网络请求前被拒绝。

```bash
# 安全状态接口：只显示提供方/模型可用性，绝不返回密钥
curl http://localhost:8001/llm/status

# 显式使用 OpenAI
curl http://localhost:8001/i18n/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Engineering review required.","target_lang":"zh","model_route":"openai","data_classification":"internal"}'

# 自动路由，并设置只允许本地处理的数据边界
curl http://localhost:8001/i18n/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Confidential claim evidence.","target_lang":"zh","model_route":"auto","data_classification":"restricted"}'
```

响应包含不带凭据的 `model_routing.trace`，记录每次提供方/模型尝试及成功状态。`POST /intake/text` 接受相同字段；文档接入和工单重新分析通过查询参数接受这两个字段。

V1.0 竞赛模式中有意跳过了演示登录环节。生产部署前请接入企业级 SSO。

## 快速开始：本地开发

### API

需要 Python 3.12（与 Docker 使用的 `python:3.12-slim` 镜像一致）。部分锁定的依赖（如 `pydantic-core`、`psycopg[binary]`）尚未为更新的 Python 版本发布预编译二进制包，如果本机 `python3 --version` 高于 3.12（例如 3.13/3.14），直接 `python3 -m venv` 可能安装失败。请显式使用 `python3.12`（例如先 `brew install python@3.12`）。

```bash
cd services/api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./globalinfra.db
uvicorn app.main:app --reload --port 8000
```

### Web

另开一个终端：

```bash
cd apps/web
npm install
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

打开 http://localhost:3000。

默认情况下，Web 端会跟随浏览器的 `Accept-Language` 自动显示中文或英文界面（通过 Cookie 记忆，无需在 URL 中切换路径），也可以点击顶部导航栏右上角的语言切换按钮手动覆盖。

## 竞赛演示路径

1. 打开 **工单（Cases）**。
2. 选择 `CASE-2026-0182`。
3. 点击 **运行 AI 分析（Run AI Analysis）**。
4. 查看专家智能体运行记录。
5. 查看证据链与核验状态。
6. 前往 **审批（Approvals）**，批准受管控的对外回复。
7. 打开 **智能体组织（Agent Organization）**，展示动态专家团队组建过程。
8. 打开 **架构（Architecture）**，追溯一个工程事件在数字主线上的完整轨迹。

种子工单数据完全是模拟且已脱敏的。

## 通用接入（Universal Intake，V1.3 M1 + M2 + M3 + M4 + M5）

"通用接入基座"把任意真实现场输入在一次调用内转化为结构化、已路由、已分析的工单；默认完全确定性、可离线运行（无需 API Key），并在配置了模型时启用可选的 LLM 分类层（M2）与结构化抽取层（M3 + M4），两层均以 schema 约束的结构化输出（M5）加固。

```text
文本 / PDF / DOCX / TXT  →  IntakeResult  →  工单（Case）  →  analyze_case  →  专家团队 + 证据 + 审批关卡
```

两个接口：

- `POST /intake/text` — 请求体 `{"text": "...", "language": "en|zh（可选）"}`。
- `POST /intake/document` — multipart 上传 `file=@...`，支持 PDF / DOCX / TXT，并校验文件签名/内容，默认大小上限为可配置的 10 MiB（`MAX_UPLOAD_BYTES`）。含文字层的文件直接进入分类和分析；有效的扫描/纯图像 PDF 会保留原件与校验和，返回 `OCR_REQUIRED` 文档回执，不会在无证据时误建工单。独立图片 OCR 与语音 ASR 仍不在此接口范围（上传 `.png`/音频返回 `400`）。

用于联网试点时，请启用 `REQUIRE_API_KEY=true`，在 API 服务配置强随机 `API_KEY`，并在 Web 服务端将同一值配置为 `API_SERVICE_KEY`。浏览器直连来源使用逗号分隔的 `CORS_ORIGINS`；两个密钥都不得通过 `NEXT_PUBLIC_*` 暴露。

文本接入与含文字层的文档返回 `{ submission_id, case_id, intake: <IntakeResult>, specialist_team: [...], analysis: {...} }`，并按请求语言本地化（`?lang=`/`Accept-Language`，与其他接口一致）。新建工单 id 为 `CASE-INTAKE-<hash>`（绝不硬编码演示 id），并送入既有检索驱动分析工作流。扫描文档则返回同一标准接入封装，其中 `case_id: null`、`analysis: null`，并给出 `OCR_REQUIRED` 的 `SourceDocument` 回执，直到获得可核验文本。

**`IntakeResult`**（见 `services/api/app/intake.py`）字段：`primary_domain`、`professional_domain`、`case_type`、`case_type_label`、`classification_method`、`extraction_method`、`lifecycle_stage`、`risk`、`risk_label`、`country`、`country_label`、`language`、`issues[]`、`entities[]`、`deadline`、`recommended_agents[]`、`required_approvals[]`、`confidence`。

- **Layer 1（确定性，默认权威层）：** `case_type` 与 `risk` 由包装既有 `classify.py` 规则产出，其 `{"type","risk"}` 契约保持不变，`/cases/classify`、评测与接入三者结论一致。
- **Layer 2（LLM 分类层，M2）：** 当配置了 OpenAI 兼容模型（`llm_mode` ≠ `mock`；云端模式需要 API Key，`local` 模式不需要）时，`app/llm_classify.py` 用模型细化 `case_type`/`risk`，并**严格约束在同一词汇表**（`workflow.SPECIALISTS_BY_CASE_TYPE` 的键 + 风险等级）内，确保结果始终可路由。只要未配置模型（默认），或调用失败、返回格式错误/越界标签，即**回退到 Layer 1 规则**——因此默认云端配置在无 Key 时与 M1 逐字节一致，全部单测与评测离线保持通过。`IntakeResult` 中的 `classification_method` 标明由哪一层判定（`"rules"`/`"llm"`）；`classify.py` 本体从不改动。
- **Layer 3（LLM 结构化抽取层，M3 + M4）：** 配置了模型时，`app/llm_extract.py` 在**同一次调用**内抽取 `country`、`issues`、`entities`（M3），以及项目 `lifecycle` 阶段与响应 `deadline`（M4）。每个字段都**严格约束在确定性启发式所用的同一词汇表**（`intake.py` 的 `COUNTRY_SIGNALS` / `ISSUE_SIGNALS` / `LIFECYCLE_SIGNALS` 表，作为单一真源——因此模型返回的任何值仍可路由到项目、仍能解析为真实的双语阶段），且对原文**落地校验**（抽取的实体，以及 `deadline` 的数字，必须在原文逐字出现——模型可在多个引用/数字中挑出**正确**的那个，却无法凭空捏造）。只要未配置模型（默认），或调用失败、返回格式错误，即**回退到确定性关键词/正则抽取**；`lifecycle` 与 `deadline` 在模型留空时**逐字段回退**，因此 LLM 路径绝不会丢失正则本可找到的值。离线时接入路径与 M1/M2 逐字节一致。`IntakeResult` 中的 `extraction_method` 标明这些字段由哪条路径产出（`"rules"`/`"llm"`）；`intake.py` 的启发式本体从不改动。
- **结构化输出（M5）：** 两个 LLM 层不再"寄望模型吐出裸 `{...}` 再正则抠出"，而是通过 `response_format` 的 JSON-schema 显式请求 schema 合法的 JSON；schema 的枚举值由解析器所校验的**同一套**受约束词汇表构建（因此 schema 与解析器永不漂移）。这是**尽力而为的加固**：`llm.generate` 在明确指向 `response_format` 的那个 `400` 上丢弃该字段并重试一次（与既有的 reasoning 模型 `temperature` 处理完全一致），且回复**始终**再经该层自己的词汇/落地校验（这些校验比任何 schema 能表达的都更严）——因此网关不支持结构化输出、或模型无视该提示时，仍能优雅降级。离线（无 Key）时整条路径处于惰性，与 M1–M4 逐字节一致。
- **富化层：** 其余字段由可审计的规则/启发式产出。`case_type_label`/`risk_label`/`issues` 为中英双语（与 `Case.type` 相同的 `{"en","zh"}` 模式）；`case_type` 的英文规范值用于通过 `workflow.SPECIALISTS_BY_CASE_TYPE` 路由专家团队。

两张表支撑该链路（见下文**数据库迁移**）：`intake_submissions`（原始输入引用、输入哈希、解析文本、检测语言、创建时间、关联 `case_id`）与 `source_documents`（文件名、文件类型、内容寻址引用、解析状态、经校验的原始字节、内容类型/大小、关联 `intake_submission_id`）。

## V2.1 可信执行闭环

V2.1 将候选决策演示升级为受管控的执行生命周期。分析阶段会生成主张/证据图和行动意图，但绝不会生成核验 PASS。人工审批只会把行动推进到 `APPROVED`，不会执行工具，也不会修改任何核验记录。

本版本首个可执行工具是 `document.generate`：它只生成带内容摘要的业主回复草案，并明确标记 `DRAFT_ONLY_NOT_SENT` 与 `external_delivery_performed: false`，不会发送邮件或对外函件。完整生命周期为：

```text
分析 → 主张/证据 → 行动意图 → 人工审批 → 执行回执 → 独立核验回执 → 关闭
```

主要接口：`POST /actions/{id}/execute`、`POST /actions/{id}/verify`、`POST /actions/{id}/close`，以及对应的工单级接口。执行受证据引用约束且具备幂等性；核验会检查审批关联、回执完整性、产物摘要、证据引用和输出契约。检查失败会保持 `VERIFICATION_FAILED`，不能直接关闭。

工单上的旧 `verification` 对象表示分析质量评分（`WARN`），不是行动成功的证明；可信执行证明分别由 `execution_receipt` 和 `verification_receipt` 提供。

## V3.0 阶段 7 生产试点

阶段 7 新增 OIDC/RBAC 身份边界、组织与项目范围、变更审计链、离线优先现场 PWA、真实孪生数据源注册、六类企业连接器契约、AI 质量发布门禁、Prometheus 兼容指标、运行限流和独立存活/就绪探针。启用边界与生产清单见[阶段 7：生产试点](docs/PHASE7_PRODUCTION_PILOT.zh-CN.md)。

## V4.0 阶段 8 运营级数字孪生

阶段 8 新增原生 WebGL/GLTF 孪生查看、模型版本与转换任务、一键生成六格式项目孪生、时序遥测与 SSE 实时流、4D 进度与 5D 健康/成本着色、带 Twin ID/事件/模型版本/时间戳引用的 Twin Copilot，以及 180 秒参赛演示模式。能力矩阵与真实接入边界见[阶段 8：运营级数字孪生](docs/PHASE8_OPERATIONAL_TWIN.zh-CN.md)。

## V4.2 阶段 9.1 参赛黄金主线与评测证据

新增 `/competition` AI 出海参赛证据页，把双语事件接入、国家/生命周期路由、国家包、知识证据、多智能体、数字孪生、人工审批、受管控执行与独立核验编排为七步可运行主线。新增 30 条版本化 AI 出海评测集、实时指标 API 与 CI 门禁；页面显示的评测数字均由实际运行生成。实现说明、评分映射和录屏路径见[阶段 9.1：参赛黄金主线与评测证据](docs/PHASE9_COMPETITION_GOLDEN_THREAD.zh-CN.md)。

## V2.0 阶段 6 数字孪生

`/twin` 已成为覆盖全生命周期、由真实数据模型支撑的孪生运行工作台，而不是一个与业务割裂的三维演示。稳定的 `Twin ID` 将空间身份、资产层级、状态历史、工程事件、WBS、进度、成本、调试、遥测、维护与受管控 AI 仿真连接起来。

一次性交付的六个阶段：

1. **孪生底座：** 稳定 ID、资产层级、IFC/GIS 引用、对象关系和带证据的状态历史。
2. **空间工作台：** 可交互基础设施场景、构件检查、风险状态和关联工程事件。
3. **4D/5D 项控：** WBS/活动映射、计划与实际对比、进度偏差和预测成本敞口。
4. **调试与移交：** 系统/试验包准备度、Punch 遗留项和文件完整度。
5. **运营孪生：** 实时传感器边界、健康阈值、异常状态和预测性维护工单。
6. **AI 场景实验室：** 以经核验的孪生数据运行工期恢复、预测性维护和能耗方案；所有运营结果保持 `AWAITING_APPROVAL`，不会直接修改资产状态。

主要接口：`GET /twin/summary`、`/twin/scene`、`/twin/objects/{twin_id}`、`/twin/controls`、`/twin/commissioning`、`/twin/operations`、`/twin/scenarios`、`/twin/agents`；`POST /twin/scenarios/{scenario_id}/run`。

仓库内的 IFC/glTF/3D Tiles 引用、BMS/SCADA 读数和场景均为合成集成样例。生产部署可通过模型转换、项目管理系统、对象存储和遥测适配器替换数据源，同时保持 Twin ID 与 API 契约不变。

## 现场作业 2.0

- **一句话上报**：默认只有一个输入框和“语音 / 拍照 / 发送”三个大按钮；项目、类型、严重程度、构件和定位收在“更多信息（可选）”中。严重程度默认“交给 AI 判断”。
- **进入智能体组织**：同步后的现场上报按接入规则分类（上报类型只作提示），风险取上报人与 AI 判断中的较高者、绝不调低，并在后台运行智能体组织；“我的上报”显示分析状态、风险复核、处置计划和可直接回答的问题（`GET /field/reports`）。
- **现场证据**：照片、视频和录音按文件签名校验（不信任声明的类型）、限制大小、按 SHA-256 去重存储（`POST /field/media`，`GET /field/media/{sha256}`）；观察只能引用本组织已上传的媒体。离线队列保存原始文件，联网后先上传再同步。
- **构件与定位**：Twin ID 从本项目构件中选择，或在浏览器支持时扫码识别；已授权定位时自动选择 150 公里内最近的项目。
- **语音**：浏览器支持时语音转文字；否则录音作为证据附件保存，不自动转写。

## 智能体组织 2.0

每个案例由一个受治理的智能体组织处理（`services/api/app/agent_org/`），所有智能体只有建议权：

- **智能体卡片**：每个智能体的职责、可用工具、证据要求、缺证据时的提问和国家定制检索词集中定义并版本化（`GET /agents/cards`）。
- **动态组队**：以案例类型的核心团队为基础，按函件中的信号加入成本、索赔、采购、设备、调试、资产等专业（最多 6 人），每位成员记录入选理由；配置模型时可在注册表内再建议至多 2 人。
- **真实工具**：知识检索（按国家过滤）、相似已办结案例、项目状态、孪生构件定位、许可关卡、工期影响、费用估算；工具只读取已有数据，缺数据时如实说明。
- **结构化结论**：主张、证据、置信度、缺口、带负责角色的建议和向人提出的问题；模型引用未由本智能体检索到的来源时降级为证据缺口。
- **协调与求助**：协调器按依赖关系（如合同立场依赖技术成因）发现冲突和缺口；配置模型时定向追问一轮，否则直接交由人工决定；智能体的问题可在对话中回答，回答后自动重新分析（`POST /cases/{id}/inputs`）。
- **计划与核验**：计划每一步都可追溯到结论、问题或治理关卡，并带负责角色和期限；核验逐条检查结论与证据。
- **可观测**：完整运行轨迹 `GET /cases/{id}/agent-run`，最近运行 `GET /agents/runs`，成绩单 `GET /agents/scorecards`；智能体组织页展示真实运行。
- **评测**：`python evals/run_agent_org_eval.py` 以 12 个合成案例检查组队、升级、计划可追溯和结论有据，已加入 CI。

每个案例最多 12 次模型调用、最多 3 个并发；模型失败时逐步退回规则，分析不中断。

## V4.3 智能助手（对话入口）

打开 Web 端默认进入 **智能助手**（`/`），原指挥中心移至 `/overview`，其余页面不变。助手是同一套受管控能力的对话入口，不是新的推理引擎：

- **上报事件 / 处理业主函件**：文本或 PDF/DOCX/TXT 经 `/intake/text`、`/intake/document` 建工单并运行专家分析，在对话中以结论卡、处置计划、依据和处理过程呈现。
- **确认项目归属**：无法识别项目的工单保持 `NEEDS_PROJECT_CONFIRMATION`，由用户在对话中选择项目，经新增的 `POST /cases/{id}/confirm-project` 重新分析后才生成受管控行动与审批事项；系统从不替用户猜项目。用户在消息中明确写出项目编号（如 `MY-RAIL-A`）视为已确认。
- **审批与可信执行**：审批、生成草稿（`DRAFT_ONLY_NOT_SENT`）、独立核验、关闭均可在对话卡片中完成，调用的是原有接口与角色校验。
- **回复草稿**：全部审批通过后点击「生成回复草稿」，配置模型时由大模型依据来函原文、专家结论与已引用证据起草中英文回复（不得承诺费用/工期/责任，未知信息以 [●] 占位，引用必须属于本工单证据，否则退回模板），草稿全文直接显示在对话中并可复制；仍标记 `DRAFT_ONLY_NOT_SENT`，并经同一套独立核验。上传文件时输入的问题（如「如何回复此信函」）作为接入血缘中的 `user_note` 记录，仅作为起草指令，不并入文档正文。
- **查法规**：调用 `/knowledge/search` 的确定性 TF-IDF 检索，沿用工作流的相关度阈值；低于阈值时明确拒答，弱相关资料折叠显示且不作为依据。
- **项目进展 / 待我审批**：汇总项目进度、工期偏差、下一关口与待审批事项。
- **敏感数据**：勾选「敏感」后以 `restricted` 分级提交，强制本地模型。

**聊天智能体（`POST /assistant/chat`）**：配置模型时，由大模型结合最近 8 轮对话理解用户意图，从固定工具中选择一个（上报事件、查法规、查已有工单、项目进展、待审批、直接回答），工具名以 JSON schema 枚举约束，工单号与项目编号必须在数据库中真实存在，否则回退到确定性关键词规则；未配置模型时只用规则，离线与 CI 结果保持确定。法规问答由模型**仅依据检索到的来源**组织回答，且必须以 `[来源编号]` 引用；未引用或引用了未检索来源的回答会被丢弃，改为只列出来源。检索同时使用用户原话与模型改写的查询，模型改写只能增加命中、不会丢失命中。审批、执行、核验、关闭不是工具，模型无法代为操作；含事件特征的消息不会被模型以闲聊回复打发。每条回复标明「大模型理解 / 规则识别 / 按你的选择」；会话仅保存在当前浏览器标签页（`sessionStorage`）。

## V4.3 阶段 10.1 统一数据接入中心

`/data-ingestion` 工作台不再假定所有输入都是事件，而是明确分为六条通道：事件与工单、文档与函件、项目主数据、企业系统连接器、BIM/GIS/数字孪生模型、IoT/遥测数据。每条通道都写入自己的原生领域对象，同时生成租户隔离的 `IngestionReceipt`，记录校验结果、接受/拒绝数量、统一映射版本、目标对象、校验和与来源血缘。只有具备可执行意义的领域变化才触发事件。

主要接口：`GET /ingestion/catalog`、`/ingestion/summary`、`/ingestion/receipts`；`POST /ingestion/project-master`。现有现场、文本/文档、连接器、孪生源、模型转换、项目工厂与遥测接口均返回同一标准接入回执。

## 数据库迁移（Alembic）

V1.3 引入 Alembic，V2.0 将其扩展到全生命周期数字孪生，V2.1 再加入可信执行闭环。离线/测试路径保持不变：`app.main.lifespan` 仍调用 `Base.metadata.create_all` + `seed()`，本地开发、CI 与评测无需迁移步骤。Alembic 是真实（Postgres）部署的受管路径。

```bash
cd services/api
# 全新/裸库 → 创建全部表（基线 + 接入表）：
DATABASE_URL=postgresql+psycopg://... alembic upgrade head

# 库中已由历史 create_all 建好表 → 先纳管基线（不重建已有表），再执行新迁移：
DATABASE_URL=postgresql+psycopg://... alembic stamp 0001
DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```

- `0001_baseline_schema`：将已有 V1.2 表结构纳入迁移基线。
- `0002_intake_tables`：新增 `intake_submissions` 与 `source_documents`。
- `0010_preserve_source_document_content`：留存经校验的原始文档字节与内容类型/大小，支持受控 OCR 交接。
- `0003_digital_twin`：新增孪生对象图谱、状态历史、工程事件、4D/5D 关联、传感器、调试、维护与受管控场景。
- `0004_trusted_execution_closure`：新增主张、受管控行动意图、执行/核验回执、内容寻址产物及待人工确认的工单路由字段。
- `0005_phase7_production_pilot`：新增组织、身份、审计事件、现场观察、真实孪生数据源、连接器同步记录与 AI 质量发布门禁。
- `0006_phase8_operational_twin`：新增运营级孪生模型、转换任务与遥测历史。
- `0007_country_knowledge`：新增受管控国家包与知识生命周期字段。
- `0008_approval_decision_audit`：新增明确的审批决策人和决策时间审计字段。
- `0009_unified_ingestion_control_plane`：为六类接入通道新增租户隔离的校验与血缘回执。

数据库 URL 由 `migrations/env.py` 从应用设置（`DATABASE_URL`/`.env`）读取，不写入 `alembic.ini`。

## 仓库结构

```text
apps/web                 Next.js 指挥中心前端
services/api             FastAPI 领域模型 + AI 运行时
packages/country-packs   国家特定的政策与术语
packages/domain-packs    铁路 / 公路 / 桥梁等领域包
workflows                受管控的工作流定义
data/demo                 模拟竞赛数据
evals                     AI 评测框架
infra                     Docker / Kubernetes / Terraform 脚手架
docs                      架构、安全、治理与演示文档
```

## 架构原则

- 完整生命周期：投标 → 规划 → 设计 → 采购 → 施工 → 调试 → 移交 → 运维
- 八大智能领域，关联 24 个专业学科
- 用数字主线关系取代部门数据孤岛
- 以工单为驱动，而非以聊天为先
- 数据保持领域原生，仅可执行变化触发事件
- 先有证据，后有结论
- 确定性工作流 + 智能体推理步骤
- 高风险对外行动需人工审批
- 可信完成前需独立核验
- 国家包承载司法辖区 / 本地化能力
- 领域包承载交通垂直行业语义
- 模型供应商抽象层
- 具备区域数据驻留能力
- 设计上支持离线 / 边缘部署

完整设计请参见 `docs/ARCHITECTURE.md`（及其中文版 `docs/ARCHITECTURE.zh-CN.md`）。

## 生产环境仍需加固的事项

V1.1 是一个扎实的竞赛/产品基础，但并不代表已具备生产认证。在企业级上线前，需要完成 SSO、密钥管理、加密对象存储、完整文档解析、区域化部署、隐私影响评估、威胁建模、漏洞管理、备份/恢复演练，以及针对各司法辖区的法律审查。
