> **Language / 语言**: [English](README.md) · 简体中文

# GlobalInfra AI V1.1

**全球交通基础设施智能与可信执行平台**

GlobalInfra AI V1.1 是一个独立的、可直接用于竞赛展示的海外交通基础设施项目平台。它建立在一个双轴模型之上：完整的项目生命周期 与 八大互联智能领域。每一个事件都通过一个有证据支撑、受管控的行动闭环来解决。

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
- API 文档：http://localhost:8000/docs
- API 健康检查：http://localhost:8000/health

V1.0 竞赛模式中有意跳过了演示登录环节。生产部署前请接入企业级 SSO。

## 快速开始：本地开发

### API

```bash
cd services/api
python3 -m venv .venv
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
