"""Agent cards: the single, versioned definition of every agent.

A card states what an agent is responsible for, which tools it may call,
how much evidence it needs before it may conclude, and what it must do when
it cannot conclude. The public directory (``GET /agents``), the team
assembler and the runtime all read the same cards, so what the
organization page shows is what actually runs.

Every specialist is advise-only: no card grants execution, approval or
external-delivery authority. Those stay human actions in the governed
workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..agents import AGENTS
from ..i18n import bi

CARD_VERSION = "2.0"

# Agents that coordinate the organization rather than analyse a discipline.
GOVERNANCE_AGENTS = ("planning", "localization", "verification")


@dataclass(frozen=True)
class AgentCard:
    id: str
    name: dict
    group: dict
    role: dict
    risk_level: str
    focus: dict
    focus_terms: str
    tools: tuple[str, ...]
    actions: tuple[dict, ...] = ()
    gap_question: dict | None = None
    country_terms: dict[str, str] = field(default_factory=dict)
    authority: str = "advise_only"
    min_confident_evidence: int = 1
    version: str = CARD_VERSION

    def payload(self) -> dict:
        return {
            "id": self.id, "name": self.name, "group": self.group, "role": self.role,
            "risk_level": self.risk_level, "focus": self.focus, "tools": list(self.tools),
            "authority": self.authority, "version": self.version,
            "governance": self.id in GOVERNANCE_AGENTS,
            "evidence_policy": bi(
                f"At least {self.min_confident_evidence} confident source must back a conclusion; otherwise the finding is recorded as an evidence gap.",
                f"结论至少需要 {self.min_confident_evidence} 条高相关来源支撑，否则记为证据缺口。",
            ),
            "escalation": self.gap_question,
            "countries": sorted(self.country_terms),
        }


def _action(en: str, zh: str, owner_en: str, owner_zh: str) -> dict:
    return {"text": bi(en, zh), "owner_role": bi(owner_en, owner_zh)}


# Discipline-specific behaviour. Search terms bias retrieval toward the
# agent's discipline; actions are what a confident finding recommends;
# the gap question is what the agent asks a human when evidence is missing.
SPECS: dict[str, dict] = {
    "contract": dict(
        focus=bi("contractual responsibility", "合同责任划分"),
        terms="contract clause responsibility matrix scope exclusion temporary works variation instruction 合同 条款 责任 矩阵 范围 除外 临时工程 变更 指令",
        tools=("knowledge.search", "case.precedents"),
        actions=(_action("Confirm the contractual position against the cited clause before replying", "依据所引条款确认合同立场后再答复", "Contract Manager", "合同经理"),),
        gap=bi("Which contract clause or written instruction governs this matter?", "该事项适用哪一条合同条款或哪一份书面指令？"),
    ),
    "cost": dict(
        focus=bi("cost and valuation", "费用与计价"),
        terms="cost valuation rate bill of quantities budget forecast variation price quantity 费用 计价 单价 工程量清单 预算 预测 变更 工程量",
        tools=("knowledge.search", "cost.estimate", "project.status"),
        actions=(_action("Value the change against contract rates and record the cost exposure", "按合同单价对变更计价并记录费用敞口", "Quantity Surveyor", "造价工程师"),),
        gap=bi("Please provide the quantities and the rate build-up for the claimed change.", "请提供所申请变更的工程量和单价分析。"),
    ),
    "claims": dict(
        focus=bi("entitlement and time", "权利与工期"),
        terms="claim entitlement notice time bar extension of time delay evidence timeline instruction 索赔 权利 通知 时效 工期延长 延误 证据 时间线 指令",
        tools=("knowledge.search", "schedule.impact", "case.precedents"),
        actions=(_action("Check notice timing and entitlement before accepting any time or cost", "在接受任何工期或费用前核查通知时效与权利依据", "Claims Manager", "索赔经理"),),
        gap=bi("When was the event first notified, and is there a written instruction for it?", "该事件最早何时通知？是否有书面指令？"),
    ),
    "engineering": dict(
        focus=bi("technical/engineering causation", "工程技术成因"),
        terms="engineering technical evidence crack location width chronology causation structural 工程 技术 证据 裂缝 位置 宽度 时序 成因",
        tools=("knowledge.search", "twin.locate"),
        actions=(_action("Record the technical facts and cause before any responsibility is assigned", "在认定责任前记录技术事实与成因", "Lead Engineer", "主任工程师"),),
        gap=bi("What are the technical facts (location, element, dimensions, chronology)?", "请提供技术事实（位置、构件、尺寸、时间顺序）。"),
    ),
    "interface": dict(
        focus=bi("cross-discipline interface coordination", "跨专业接口协调"),
        terms="interface civil mep rail systems external boundary coordination earthwork 接口 土建 机电 轨道 系统 边界 协调 土方",
        tools=("knowledge.search", "twin.locate"),
        actions=(_action("Hold a joint interface review and agree the boundary in writing", "召开接口联合复核并书面确认边界", "Interface Manager", "接口经理"),),
        gap=bi("Which package and party own the interface boundary here?", "该接口边界归属哪个标段和哪一方？"),
    ),
    "hse": dict(
        focus=bi("safety and environmental control", "安全与环境管控"),
        terms="safety environment hazard control fall protection working at height ppe 安全 环境 危险源 管控 坠落 防护 高处作业",
        tools=("knowledge.search", "twin.locate", "permit.gates"),
        actions=(_action("Stop the unsafe activity and verify controls before restart", "停止不安全作业，复工前核实管控措施", "HSE Manager", "HSE 经理"),),
        gap=bi("Which control measures were in place at the time of the observation?", "发现问题时现场有哪些管控措施？"),
        country=dict(MY="DOSH OSHA Act 514 CIDB", ID="K3 SMK3", SA="OSH regulations", AE="MOHRE OHS"),
    ),
    "compliance": dict(
        focus=bi("local compliance and permitting", "当地合规与许可"),
        terms="compliance permit local law regulation method statement approval registration 合规 许可 当地法规 施工方案 审批 注册",
        tools=("knowledge.search", "permit.gates"),
        actions=(_action("Confirm the permit and registration gates with the competent authority", "向主管机关确认许可和注册关卡", "Compliance Manager", "合规经理"),),
        gap=bi("Which local permits or registrations already exist for this work?", "该作业目前已具备哪些当地许可或注册？"),
        country=dict(MY="CIDB DOSH registration permit", ID="OSS NIB PBG SLF", SA="Balady SBC licence", AE="Civil Defence NOC"),
    ),
    "workforce": dict(
        focus=bi("workforce competency and training", "人力资质与培训"),
        terms="workforce competency training productivity localization registration 人力 能力 资质 培训 生产率 本地化 注册",
        tools=("knowledge.search",),
        actions=(_action("Verify competency records and deliver toolbox training in the local language", "核查资质记录并以当地语言开展班前培训", "Training Lead", "培训负责人"),),
        gap=bi("Do the workers involved hold the required competency records?", "涉及的作业人员是否具备所需资质记录？"),
        country=dict(MY="CIDB personnel registration Bahasa Melayu"),
    ),
    "quality": dict(
        focus=bi("inspection and defect disposition", "检验与缺陷处置"),
        terms="quality inspection ncr defect corrective action trend crack honeycomb 质量 检验 不符合项 缺陷 纠正措施 趋势 裂缝 蜂窝",
        tools=("knowledge.search", "twin.locate", "case.precedents"),
        actions=(_action("Raise or close the NCR with a verified corrective action", "以经验证的纠正措施提出或关闭不符合项", "QA/QC Manager", "质量经理"),),
        gap=bi("Is there an inspection record or ITP hold point for this element?", "该构件是否有检验记录或 ITP 停检点？"),
    ),
    "construction": dict(
        focus=bi("site execution and work packages", "现场施工与工作包"),
        terms="construction work package method site condition progress 施工 工作包 方法 现场条件 进度",
        tools=("knowledge.search", "project.status"),
        actions=(_action("Adjust the work package sequence and brief the site team", "调整工作包顺序并向现场班组交底", "Construction Manager", "施工经理"),),
        gap=bi("Which work package and crew are affected?", "受影响的是哪个工作包和班组？"),
    ),
    "knowledge": dict(
        focus=bi("approved project precedent", "已批准的项目先例"),
        terms="knowledge approved project memory standards lessons learned 知识 项目记忆 标准 经验教训",
        tools=("knowledge.search", "case.precedents"),
        actions=(_action("Apply the approved precedent and record the lesson learned", "参照已批准先例并记录经验教训", "Document Controller", "文控负责人"),),
        gap=None,
    ),
    "procurement": dict(
        focus=bi("procurement and supply", "采购与供应"),
        terms="procurement supplier delivery lead time purchase order 采购 供应商 交付 周期 订单",
        tools=("knowledge.search", "project.status"),
        actions=(_action("Confirm supplier lead time and delivery commitments", "确认供应商交付周期与承诺", "Procurement Manager", "采购经理"),),
        gap=bi("Which supplier and purchase order are involved, and what is the promised delivery date?", "涉及哪家供应商和哪张订单？承诺交付日期是什么？"),
    ),
    "plant": dict(
        focus=bi("plant and equipment readiness", "机械设备就绪"),
        terms="plant equipment crane lifting maintenance breakdown utilization inspection certificate 设备 起重机 吊装 维护 故障 利用率 检验证书",
        tools=("knowledge.search", "permit.gates"),
        actions=(_action("Verify equipment inspection certificates before use", "使用前核验设备检验证书", "Plant Manager", "设备经理"),),
        gap=bi("Is there a valid inspection certificate for the equipment involved?", "涉及的设备是否有有效检验证书？"),
    ),
    "commissioning": dict(
        focus=bi("testing and commissioning readiness", "测试与调试就绪"),
        terms="commissioning testing punch list handover system readiness 调试 测试 遗留项 移交 系统就绪",
        tools=("knowledge.search", "twin.locate"),
        actions=(_action("Update the system readiness and punch list status", "更新系统就绪度与遗留项状态", "Commissioning Manager", "调试经理"),),
        gap=bi("Which system and test pack does this affect?", "受影响的是哪个系统和哪个试验包？"),
    ),
    "asset": dict(
        focus=bi("asset handover and operations", "资产移交与运维"),
        terms="asset register handover maintenance operations 资产 台账 移交 维护 运营",
        tools=("knowledge.search", "twin.locate"),
        actions=(_action("Update the asset register and maintenance plan", "更新资产台账与维护计划", "Asset Manager", "资产经理"),),
        gap=bi("Which asset tag and maintenance plan apply?", "适用哪个资产编号和维护计划？"),
    ),
    "risk": dict(
        focus=bi("risk exposure and mitigation", "风险敞口与缓解"),
        terms="risk exposure probability impact mitigation contingency 风险 敞口 概率 影响 缓解 应急",
        tools=("knowledge.search", "project.status", "case.precedents"),
        actions=(_action("Record the risk in the register with an owner and mitigation", "将风险登记入册并指定负责人与缓解措施", "Risk Manager", "风险经理"),),
        gap=None,
    ),
    "planning": dict(focus=bi("schedule and response plan", "进度与响应计划"), terms="schedule critical path delay recovery programme 进度 关键路径 延误 恢复 计划", tools=("schedule.impact", "project.status")),
    "localization": dict(focus=bi("bilingual terminology", "双语术语"), terms="", tools=("terminology.lock",)),
    "verification": dict(focus=bi("evidence verification", "证据核验"), terms="", tools=("evidence.verify",)),
}


def _build() -> dict[str, AgentCard]:
    cards = {}
    for agent in AGENTS:
        spec = SPECS.get(agent["id"])
        if spec is None:
            continue
        cards[agent["id"]] = AgentCard(
            id=agent["id"], name=agent["name"], group=agent["group"], role=agent["role"],
            risk_level=agent["risk_level"], focus=spec["focus"], focus_terms=spec["terms"],
            tools=spec["tools"], actions=spec.get("actions", ()), gap_question=spec.get("gap"),
            country_terms=spec.get("country", {}),
        )
    return cards


CARDS: dict[str, AgentCard] = _build()
SPECIALIST_IDS: tuple[str, ...] = tuple(card_id for card_id in CARDS if card_id not in GOVERNANCE_AGENTS)
