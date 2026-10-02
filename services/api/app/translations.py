"""Deterministic offline fallback for the translation-model integration.

When no real OpenAI-compatible model is configured (``llm_mode=mock``, the
default for local dev / CI / the eval harness) ``llm.translate()`` resolves
English runtime text through this curated phrase table instead of calling
out to the network. Every string below is text that the workflow engine
(`workflow.py`) and governance endpoints (`main.py`) actually produce, so the
bilingual experience stays fully deterministic without external calls.

When ``OPENAI_COMPAT_API_KEY`` is set and ``llm_mode`` is not "mock", the
same call sites go through the real model instead (see ``llm.translate``).
"""

DEMO_TRANSLATIONS: dict[str, dict[str, str]] = {
    "Normalized 2 issues and preserved source-language context.": {
        "zh": "已规范化 2 项问题，并保留原始语言语境。"
    },
    "Normalized 3 issues and preserved source-language context.": {
        "zh": "已规范化 3 项问题，并保留原始语言语境。"
    },
    "Found responsibility and temporary-works evidence; external-road scope must not be assumed without the responsibility matrix.": {
        "zh": "已找到责任划分与临时工程相关证据；在未核对责任矩阵前，不得假定外部道路范围属于承包商责任。"
    },
    "Crack responsibility cannot be assigned from the notice alone; crack location, width, chronology and causation evidence are required.": {
        "zh": "仅凭通知函无法判定裂缝责任归属；需补充裂缝位置、宽度、发生时序及成因证据。"
    },
    "No unsupported local-law conclusion generated; response remains limited to the approved synthetic project evidence set.": {
        "zh": "未生成缺乏依据的当地法律结论；回复内容仅限于已批准的项目证据集合。"
    },
    "Prepared terminology-locked bilingual response context while preserving defined contractual terms.": {
        "zh": "已准备术语锁定的双语回复上下文，并保留合同既定术语的准确含义。"
    },
    "Created a six-step response plan: confirm scope, coordinate earthwork boundary, inspect crack, compile evidence, draft response, obtain Project Manager approval.": {
        "zh": "已生成六步响应计划：确认范围、协调土方边界、现场核查裂缝、汇总证据、起草回函、获取项目经理审批。"
    },
    "Completed initial discipline review and identified evidence gaps.": {
        "zh": "已完成初步专业评审，并识别出证据缺口。"
    },
    "Generated governed action plan and human review checkpoint.": {
        "zh": "已生成受管控的行动计划，并设置人工复核节点。"
    },
    "Verified cited evidence and blocked external execution until required human approval is recorded.": {
        "zh": "已核实引用证据，并在获得所需人工审批前阻止对外执行。"
    },
    "Approve external response / governed action": {
        "zh": "审批对外回复 / 受管控行动"
    },
    "Analysis completed; external action is gated by approval.": {
        "zh": "分析已完成；对外行动需经审批后方可执行。"
    },
    "Evidence-backed candidate action generated": {
        "zh": "已生成有证据支撑的候选行动"
    },
    "External action blocked pending human approval": {
        "zh": "对外行动已阻止，待人工审批"
    },
    "Required human approval recorded": {
        "zh": "已记录所需的人工审批"
    },
    "Trusted execution may proceed": {
        "zh": "可信执行流程可以继续"
    },
    "Deterministic demo mode active. No external model call was required.": {
        "zh": "确定性演示模式已启用，本次未调用外部模型。"
    },
}
