"""Canonical project-intelligence taxonomy for the GlobalInfra platform.

The competition UI only activates a subset of these capabilities, but every
project event is classified against the complete lifecycle and domain model.
"""
from .i18n import bi

LIFECYCLE_STAGES = [
    {"id": "opportunity", "name": bi("Opportunity & Tender", "商机与投标"), "short": bi("Tender", "投标"), "order": 1},
    {"id": "planning", "name": bi("Planning", "规划"), "short": bi("Plan", "规划"), "order": 2},
    {"id": "design", "name": bi("Design", "设计"), "short": bi("Design", "设计"), "order": 3},
    {"id": "procurement", "name": bi("Procurement", "采购"), "short": bi("Procure", "采购"), "order": 4},
    {"id": "construction", "name": bi("Construction", "施工"), "short": bi("Build", "施工"), "order": 5},
    {"id": "commissioning", "name": bi("Testing & Commissioning", "测试与调试"), "short": bi("Test", "测试"), "order": 6},
    {"id": "handover", "name": bi("Handover", "移交"), "short": bi("Handover", "移交"), "order": 7},
    {"id": "operations", "name": bi("Operation & Maintenance", "运行与维护"), "short": bi("Operate", "运维"), "order": 8},
]

INTELLIGENCE_DOMAINS = [
    {"id":"project","name":bi("Project Intelligence","项目智能"),"number":"01","question":bi("What is the real status of the project right now?","项目现在到底怎么样？"),"accent":"cyan","capabilities":[bi("Portfolio","项目组合"),bi("Project Controls","项目管控"),bi("Schedule","进度"),bi("Cost","成本"),bi("Progress","完成情况"),bi("Forecast","预测"),bi("Performance","绩效"),bi("Risk","风险"),bi("Change","变更")]},
    {"id":"engineering","name":bi("Engineering Intelligence","工程智能"),"number":"02","question":bi("What is the right technical solution?","技术上应该怎么做？"),"accent":"blue","capabilities":[bi("Design","设计"),bi("Drawings","图纸"),bi("Specifications","规范"),bi("RFI","技术问询"),bi("Technical Query","技术问题"),bi("Design Review","设计审查"),bi("Interfaces","接口"),bi("BIM / GIS","BIM / GIS"),bi("Engineering Decisions","工程决策")]},
    {"id":"delivery","name":bi("Delivery Intelligence","交付智能"),"number":"03","question":bi("How does the project actually get built?","项目怎么真正建出来？"),"accent":"orange","capabilities":[bi("Construction","施工"),bi("Work Packages","工作包"),bi("Method Statements","施工方案"),bi("Daily Progress","日进度"),bi("Procurement","采购"),bi("Supply Chain","供应链"),bi("Materials","材料"),bi("Plant","机械设备"),bi("Logistics","物流"),bi("Commissioning","调试")]},
    {"id":"commercial","name":bi("Commercial Intelligence","商务智能"),"number":"04","question":bi("Who is responsible? How much does it cost? What are the rights and obligations?","谁负责？多少钱？有哪些权利与义务？"),"accent":"violet","capabilities":[bi("Contract","合同"),bi("Scope","范围"),bi("Responsibility","责任"),bi("Variation","变更"),bi("Claim","索赔"),bi("EOT","工期延长"),bi("Payment","付款"),bi("Subcontract","分包"),bi("Commercial Risk","商务风险"),bi("Correspondence","函件往来")]},
    {"id":"assurance","name":bi("Risk & Assurance Intelligence","风险与保证智能"),"number":"05","question":bi("Is risk under control, and is delivery trustworthy?","风险是否受控，交付是否可信？"),"accent":"red","capabilities":[bi("HSE","健康安全环保"),bi("Quality","质量"),bi("Compliance","合规"),bi("Permits","许可"),bi("Environment","环境"),bi("Audit","审计"),bi("Inspection","检验"),bi("NCR","不符合项"),bi("Incident","事故"),bi("Corrective Action","纠正措施"),bi("Verification","核验")]},
    {"id":"resources","name":bi("Workforce & Resource Intelligence","人力与资源智能"),"number":"06","question":bi("Do people, skills and equipment match delivery needs?","人员、技能与设备是否匹配交付需求？"),"accent":"green","capabilities":[bi("Workforce","人力"),bi("Competency","能力资质"),bi("Training","培训"),bi("Productivity","生产率"),bi("Equipment","设备"),bi("Plant","机械设备"),bi("Resource Forecast","资源预测"),bi("Shift","班次"),bi("Certification","资质认证"),bi("Localization","本地化")]},
    {"id":"knowledge","name":bi("Knowledge & Collaboration Intelligence","知识与协作智能"),"number":"07","question":bi("What does the organization know, and who should know it?","组织知道什么，谁应该知道？"),"accent":"teal","capabilities":[bi("Documents","文档"),bi("Knowledge Base","知识库"),bi("Knowledge Graph","知识图谱"),bi("Lessons Learned","经验教训"),bi("Meeting","会议"),bi("Correspondence","函件往来"),bi("Translation","翻译"),bi("Project Memory","项目记忆"),bi("Stakeholders","相关方")]},
    {"id":"assets","name":bi("Asset & Operations Intelligence","资产与运维智能"),"number":"08","question":bi("How is project capability extended across the asset lifecycle?","如何把项目能力延伸到资产全寿命？"),"accent":"amber","capabilities":[bi("Asset Registry","资产台账"),bi("Commissioning","调试"),bi("Handover","移交"),bi("Inspection","检验"),bi("Condition","状态"),bi("Maintenance","维护"),bi("Failure","故障"),bi("Digital Twin","数字孪生"),bi("Operations","运行"),bi("Predictive Maintenance","预测性维护")]},
]

# (english name, chinese name, english scope, chinese scope, parent intelligence domain id)
PROFESSIONAL_DOMAINS = [
    ("Project Controls", "项目管控", "Schedule, cost, planning, performance, forecast", "进度、成本、计划、绩效、预测", "project"),
    ("Engineering", "工程", "Technical solutions, design coordination, RFI, technical queries", "技术方案、设计协调、RFI、技术问题", "engineering"),
    ("Design Management", "设计管理", "Drawings, design review, change, interfaces", "图纸、设计审查、变更、接口", "engineering"),
    ("Construction", "施工", "Site activities, field issues, methods, resources", "施工活动、现场问题、方法、资源", "delivery"),
    ("Contract & Commercial", "合同与商务", "Contract, responsibility, claims, payment, change", "合同、责任、索赔、支付、变更", "commercial"),
    ("Procurement", "采购", "Sourcing, suppliers, materials, delivery", "采购、供应商、材料、交付", "delivery"),
    ("Quality", "质量", "ITP, inspection, NCR, defects, quality trends", "ITP、Inspection、NCR、缺陷、质量趋势", "assurance"),
    ("HSE", "健康安全环保（HSE）", "Safety, environment, incidents, training, risk", "安全、环境、Incident、Training、Risk", "assurance"),
    ("Planning & Schedule", "计划与进度", "WBS, critical path, delay, lookahead", "WBS、关键路径、延误、Lookahead", "project"),
    ("Cost & Finance", "成本与财务", "Budget, committed cost, forecast, cash flow", "Budget、Committed Cost、Forecast、Cash Flow", "project"),
    ("Risk & Opportunity", "风险与机会", "Project risk, opportunity, response actions", "项目风险、机会、应对措施", "project"),
    ("Change Management", "变更管理", "Design / scope / contract change", "Design / Scope / Contract Change", "project"),
    ("Document Control", "文档管控", "Drawings, specifications, correspondence, revisions, transmittals", "图纸、规范、函件、版本、Transmittal", "knowledge"),
    ("Stakeholder & Communication", "相关方与沟通", "Owner, supervision, government, subcontractors, meetings, correspondence", "业主、监理、政府、分包商、会议、函件", "knowledge"),
    ("Workforce", "人力资源", "People, skills, training, qualification, productivity", "人员、技能、培训、资质、生产率", "resources"),
    ("Plant & Equipment", "机械设备", "Machinery, equipment, utilization, maintenance", "机械、设备、利用率、检修", "resources"),
    ("Materials & Logistics", "材料与物流", "Materials, inventory, transport, site logistics", "材料、库存、运输、现场物流", "delivery"),
    ("Compliance & Permits", "合规与许可", "Regulations, permits, government approvals", "法规、许可证、政府审批", "assurance"),
    ("Environment & ESG", "环境与 ESG", "Environment, carbon, social impact, sustainability", "环境、碳排、社会影响、可持续性", "assurance"),
    ("Interface Management", "接口管理", "Civil / MEP / rail / systems / external interfaces", "土建 / 机电 / 轨道 / 系统 / 外部接口", "engineering"),
    ("Commissioning", "调试", "Testing, commissioning, punch list, handover", "测试、调试、Punch List、移交", "assets"),
    ("Asset & O&M", "资产与运维", "Assets, maintenance, inspection, operating condition", "资产、维护、检测、运行状态", "assets"),
    ("Knowledge & Lessons Learned", "知识与经验教训", "Knowledge assets, experience, best practices", "知识资产、经验、标准做法", "knowledge"),
    ("Claims & Disputes", "索赔与争议", "EOT, variation, claim, evidence chain, disputes", "EOT、Variation、Claim、证据链、争议", "commercial"),
]

TRUSTED_ACTION_STAGES = [bi("Event", "事件"), bi("Case", "工单"), bi("Evidence", "证据"), bi("Decision", "决策"), bi("Action", "行动"), bi("Verification", "核验")]

PROJECT_INTELLIGENCE = {
    1: {"phase":"construction","progress":62.4,"budget":2840,"committed":2176,"forecast":2916,"schedule_variance":-18,"next_gate":bi("Systems integration readiness","系统集成就绪度"),"gate_date":"18 Oct 2026"},
    2: {"phase":"procurement","progress":38.7,"budget":1680,"committed":912,"forecast":1654,"schedule_variance":4,"next_gate":bi("Pavement package award","路面标段授标"),"gate_date":"03 Nov 2026"},
    3: {"phase":"design","progress":24.1,"budget":5120,"committed":1385,"forecast":5248,"schedule_variance":-11,"next_gate":bi("60% design freeze","60% 设计冻结"),"gate_date":"26 Oct 2026"},
}

DOMAIN_HEALTH = {
    "project": {"health":78,"trend":"-3.2%","signal":bi("Schedule recovery required","需进行进度抢赶"),"open":7},
    "engineering": {"health":84,"trend":"+1.8%","signal":bi("12 RFIs awaiting closure","12 项技术问询待关闭"),"open":12},
    "delivery": {"health":81,"trend":"+0.6%","signal":bi("Three work fronts constrained","三个工作面受限"),"open":9},
    "commercial": {"health":72,"trend":"-4.1%","signal":bi("2 notices inside response window","2 份通知处于响应窗口期内"),"open":5},
    "assurance": {"health":88,"trend":"+2.4%","signal":bi("One critical HSE action","1 项紧急 HSE 行动"),"open":8},
    "resources": {"health":86,"trend":"+1.1%","signal":bi("Competency coverage 94%","能力资质覆盖率 94%"),"open":4},
    "knowledge": {"health":91,"trend":"+3.5%","signal":bi("96% evidence traceability","96% 证据可追溯率"),"open":3},
    "assets": {"health":67,"trend":"+0.9%","signal":bi("Handover model in preparation","移交模型准备中"),"open":6},
}

def professional_domains():
    return [{"id": en_name.lower().replace(" & ", "-").replace(" ", "-"), "name": bi(en_name, zh_name), "scope": bi(scope_en, scope_zh), "intelligence_domain": parent} for en_name, zh_name, scope_en, scope_zh, parent in PROFESSIONAL_DOMAINS]
