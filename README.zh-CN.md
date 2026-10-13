> **Language / 语言**: [English](README.md) · 简体中文

# GlobalInfra AI V3.0

**全球交通基础设施智能与可信执行平台**

GlobalInfra AI V3.0 是一个独立的、面向真实海外交通基础设施项目生产试点的平台。它建立在完整项目生命周期与八大互联智能领域组成的双轴模型之上，每一个事件都通过有证据支撑、受管控的行动闭环解决。

> 范围说明：本仓库是一个全新的独立代码库。它不依赖、不导入、不调用、也不暴露 TheOne 或任何 TheOne 品牌的运行时。

## V1.1 中可运行的能力

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
- `POST /intake/document` — multipart 上传 `file=@...`。M1 **仅做文字抽取**（PDF / DOCX / TXT），并校验文件签名/内容，默认大小上限为可配置的 10 MiB（`MAX_UPLOAD_BYTES`）。图片 OCR 与语音 ASR 明确不在 M1 范围（上传 `.png`/音频返回 `400`）。

用于联网试点时，请启用 `REQUIRE_API_KEY=true`，在 API 服务配置强随机 `API_KEY`，并在 Web 服务端将同一值配置为 `API_SERVICE_KEY`。浏览器直连来源使用逗号分隔的 `CORS_ORIGINS`；两个密钥都不得通过 `NEXT_PUBLIC_*` 暴露。

两者均返回 `{ submission_id, case_id, intake: <IntakeResult>, specialist_team: [...], analysis: {...} }`，并按请求语言本地化（`?lang=`/`Accept-Language`，与其他接口一致）。新建工单 id 为 `CASE-INTAKE-<hash>`（绝不硬编码演示 id），并送入既有检索驱动分析工作流，因此响应中可直接看到工单 id 与已组建的专家团队。

**`IntakeResult`**（见 `services/api/app/intake.py`）字段：`primary_domain`、`professional_domain`、`case_type`、`case_type_label`、`classification_method`、`extraction_method`、`lifecycle_stage`、`risk`、`risk_label`、`country`、`country_label`、`language`、`issues[]`、`entities[]`、`deadline`、`recommended_agents[]`、`required_approvals[]`、`confidence`。

- **Layer 1（确定性，默认权威层）：** `case_type` 与 `risk` 由包装既有 `classify.py` 规则产出，其 `{"type","risk"}` 契约保持不变，`/cases/classify`、评测与接入三者结论一致。
- **Layer 2（LLM 分类层，M2）：** 当配置了 OpenAI 兼容模型（`llm_mode` ≠ `mock`；云端模式需要 API Key，`local` 模式不需要）时，`app/llm_classify.py` 用模型细化 `case_type`/`risk`，并**严格约束在同一词汇表**（`workflow.SPECIALISTS_BY_CASE_TYPE` 的键 + 风险等级）内，确保结果始终可路由。只要未配置模型（默认），或调用失败、返回格式错误/越界标签，即**回退到 Layer 1 规则**——因此默认云端配置在无 Key 时与 M1 逐字节一致，全部单测与评测离线保持通过。`IntakeResult` 中的 `classification_method` 标明由哪一层判定（`"rules"`/`"llm"`）；`classify.py` 本体从不改动。
- **Layer 3（LLM 结构化抽取层，M3 + M4）：** 配置了模型时，`app/llm_extract.py` 在**同一次调用**内抽取 `country`、`issues`、`entities`（M3），以及项目 `lifecycle` 阶段与响应 `deadline`（M4）。每个字段都**严格约束在确定性启发式所用的同一词汇表**（`intake.py` 的 `COUNTRY_SIGNALS` / `ISSUE_SIGNALS` / `LIFECYCLE_SIGNALS` 表，作为单一真源——因此模型返回的任何值仍可路由到项目、仍能解析为真实的双语阶段），且对原文**落地校验**（抽取的实体，以及 `deadline` 的数字，必须在原文逐字出现——模型可在多个引用/数字中挑出**正确**的那个，却无法凭空捏造）。只要未配置模型（默认），或调用失败、返回格式错误，即**回退到确定性关键词/正则抽取**；`lifecycle` 与 `deadline` 在模型留空时**逐字段回退**，因此 LLM 路径绝不会丢失正则本可找到的值。离线时接入路径与 M1/M2 逐字节一致。`IntakeResult` 中的 `extraction_method` 标明这些字段由哪条路径产出（`"rules"`/`"llm"`）；`intake.py` 的启发式本体从不改动。
- **结构化输出（M5）：** 两个 LLM 层不再"寄望模型吐出裸 `{...}` 再正则抠出"，而是通过 `response_format` 的 JSON-schema 显式请求 schema 合法的 JSON；schema 的枚举值由解析器所校验的**同一套**受约束词汇表构建（因此 schema 与解析器永不漂移）。这是**尽力而为的加固**：`llm.generate` 在明确指向 `response_format` 的那个 `400` 上丢弃该字段并重试一次（与既有的 reasoning 模型 `temperature` 处理完全一致），且回复**始终**再经该层自己的词汇/落地校验（这些校验比任何 schema 能表达的都更严）——因此网关不支持结构化输出、或模型无视该提示时，仍能优雅降级。离线（无 Key）时整条路径处于惰性，与 M1–M4 逐字节一致。
- **富化层：** 其余字段由可审计的规则/启发式产出。`case_type_label`/`risk_label`/`issues` 为中英双语（与 `Case.type` 相同的 `{"en","zh"}` 模式）；`case_type` 的英文规范值用于通过 `workflow.SPECIALISTS_BY_CASE_TYPE` 路由专家团队。

新增两张表（见下文**数据库迁移**）：`intake_submissions`（原始输入引用、输入哈希、解析文本、检测语言、创建时间、关联 `case_id`）与 `source_documents`（文件名、文件类型、存储引用、解析状态、关联 `intake_submission_id`）。

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
- `0003_digital_twin`：新增孪生对象图谱、状态历史、工程事件、4D/5D 关联、传感器、调试、维护与受管控场景。
- `0004_trusted_execution_closure`：新增主张、受管控行动意图、执行/核验回执、内容寻址产物及待人工确认的工单路由字段。
- `0005_phase7_production_pilot`：新增组织、身份、审计事件、现场观察、真实孪生数据源、连接器同步记录与 AI 质量发布门禁。

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
