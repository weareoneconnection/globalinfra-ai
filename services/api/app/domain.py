"""Canonical project-intelligence taxonomy for the GlobalInfra platform.

The competition UI only activates a subset of these capabilities, but every
project event is classified against the complete lifecycle and domain model.
"""

LIFECYCLE_STAGES = [
    {"id": "opportunity", "name": "Opportunity & Tender", "short": "Tender", "order": 1},
    {"id": "planning", "name": "Planning", "short": "Plan", "order": 2},
    {"id": "design", "name": "Design", "short": "Design", "order": 3},
    {"id": "procurement", "name": "Procurement", "short": "Procure", "order": 4},
    {"id": "construction", "name": "Construction", "short": "Build", "order": 5},
    {"id": "commissioning", "name": "Testing & Commissioning", "short": "Test", "order": 6},
    {"id": "handover", "name": "Handover", "short": "Handover", "order": 7},
    {"id": "operations", "name": "Operation & Maintenance", "short": "Operate", "order": 8},
]

INTELLIGENCE_DOMAINS = [
    {"id":"project","name":"Project Intelligence","number":"01","question":"项目现在到底怎么样？","accent":"cyan","capabilities":["Portfolio","Project Controls","Schedule","Cost","Progress","Forecast","Performance","Risk","Change"]},
    {"id":"engineering","name":"Engineering Intelligence","number":"02","question":"技术上应该怎么做？","accent":"blue","capabilities":["Design","Drawings","Specifications","RFI","Technical Query","Design Review","Interfaces","BIM / GIS","Engineering Decisions"]},
    {"id":"delivery","name":"Delivery Intelligence","number":"03","question":"项目怎么真正建出来？","accent":"orange","capabilities":["Construction","Work Packages","Method Statements","Daily Progress","Procurement","Supply Chain","Materials","Plant","Logistics","Commissioning"]},
    {"id":"commercial","name":"Commercial Intelligence","number":"04","question":"谁负责？多少钱？有哪些权利与义务？","accent":"violet","capabilities":["Contract","Scope","Responsibility","Variation","Claim","EOT","Payment","Subcontract","Commercial Risk","Correspondence"]},
    {"id":"assurance","name":"Risk & Assurance Intelligence","number":"05","question":"风险是否受控，交付是否可信？","accent":"red","capabilities":["HSE","Quality","Compliance","Permits","Environment","Audit","Inspection","NCR","Incident","Corrective Action","Verification"]},
    {"id":"resources","name":"Workforce & Resource Intelligence","number":"06","question":"人员、技能与设备是否匹配交付需求？","accent":"green","capabilities":["Workforce","Competency","Training","Productivity","Equipment","Plant","Resource Forecast","Shift","Certification","Localization"]},
    {"id":"knowledge","name":"Knowledge & Collaboration Intelligence","number":"07","question":"组织知道什么，谁应该知道？","accent":"teal","capabilities":["Documents","Knowledge Base","Knowledge Graph","Lessons Learned","Meeting","Correspondence","Translation","Project Memory","Stakeholders"]},
    {"id":"assets","name":"Asset & Operations Intelligence","number":"08","question":"如何把项目能力延伸到资产全寿命？","accent":"amber","capabilities":["Asset Registry","Commissioning","Handover","Inspection","Condition","Maintenance","Failure","Digital Twin","Operations","Predictive Maintenance"]},
]

PROFESSIONAL_DOMAINS = [
    ("Project Controls", "进度、成本、计划、绩效、预测", "project"),
    ("Engineering", "技术方案、设计协调、RFI、技术问题", "engineering"),
    ("Design Management", "图纸、设计审查、变更、接口", "engineering"),
    ("Construction", "施工活动、现场问题、方法、资源", "delivery"),
    ("Contract & Commercial", "合同、责任、索赔、支付、变更", "commercial"),
    ("Procurement", "采购、供应商、材料、交付", "delivery"),
    ("Quality", "ITP、Inspection、NCR、缺陷、质量趋势", "assurance"),
    ("HSE", "安全、环境、Incident、Training、Risk", "assurance"),
    ("Planning & Schedule", "WBS、关键路径、延误、Lookahead", "project"),
    ("Cost & Finance", "Budget、Committed Cost、Forecast、Cash Flow", "project"),
    ("Risk & Opportunity", "项目风险、机会、应对措施", "project"),
    ("Change Management", "Design / Scope / Contract Change", "project"),
    ("Document Control", "图纸、规范、函件、版本、Transmittal", "knowledge"),
    ("Stakeholder & Communication", "业主、监理、政府、分包商、会议、函件", "knowledge"),
    ("Workforce", "人员、技能、培训、资质、生产率", "resources"),
    ("Plant & Equipment", "机械、设备、利用率、检修", "resources"),
    ("Materials & Logistics", "材料、库存、运输、现场物流", "delivery"),
    ("Compliance & Permits", "法规、许可证、政府审批", "assurance"),
    ("Environment & ESG", "环境、碳排、社会影响、可持续性", "assurance"),
    ("Interface Management", "土建 / 机电 / 轨道 / 系统 / 外部接口", "engineering"),
    ("Commissioning", "测试、调试、Punch List、移交", "assets"),
    ("Asset & O&M", "资产、维护、检测、运行状态", "assets"),
    ("Knowledge & Lessons Learned", "知识资产、经验、标准做法", "knowledge"),
    ("Claims & Disputes", "EOT、Variation、Claim、证据链、争议", "commercial"),
]

TRUSTED_ACTION_STAGES = ["Event", "Case", "Evidence", "Decision", "Action", "Verification"]

PROJECT_INTELLIGENCE = {
    1: {"phase":"construction","progress":62.4,"budget":2840,"committed":2176,"forecast":2916,"schedule_variance":-18,"next_gate":"Systems integration readiness","gate_date":"18 Oct 2026"},
    2: {"phase":"procurement","progress":38.7,"budget":1680,"committed":912,"forecast":1654,"schedule_variance":4,"next_gate":"Pavement package award","gate_date":"03 Nov 2026"},
    3: {"phase":"design","progress":24.1,"budget":5120,"committed":1385,"forecast":5248,"schedule_variance":-11,"next_gate":"60% design freeze","gate_date":"26 Oct 2026"},
}

DOMAIN_HEALTH = {
    "project": {"health":78,"trend":"-3.2%","signal":"Schedule recovery required","open":7},
    "engineering": {"health":84,"trend":"+1.8%","signal":"12 RFIs awaiting closure","open":12},
    "delivery": {"health":81,"trend":"+0.6%","signal":"Three work fronts constrained","open":9},
    "commercial": {"health":72,"trend":"-4.1%","signal":"2 notices inside response window","open":5},
    "assurance": {"health":88,"trend":"+2.4%","signal":"One critical HSE action","open":8},
    "resources": {"health":86,"trend":"+1.1%","signal":"Competency coverage 94%","open":4},
    "knowledge": {"health":91,"trend":"+3.5%","signal":"96% evidence traceability","open":3},
    "assets": {"health":67,"trend":"+0.9%","signal":"Handover model in preparation","open":6},
}

def professional_domains():
    return [{"id": name.lower().replace(" & ", "-").replace(" ", "-"), "name": name, "scope": scope, "intelligence_domain": parent} for name, scope, parent in PROFESSIONAL_DOMAINS]
