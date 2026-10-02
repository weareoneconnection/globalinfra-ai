// Structured demo signal data for the Intelligence domain pages. This is
// frontend-local mock content (not served by the API), so it is kept
// bilingual here rather than in the messages/*.json UI-chrome catalogs.
export type Scenario = { title: string; meta: string; status: string };

const EN: Record<string, Scenario[]> = {
  project: [
    { title: 'Critical path recovery · Section C4', meta: '18-day variance · 3 linked work packages', status: 'ACTION' },
    { title: 'Forecast at completion exposure', meta: '+76M · driven by design change and acceleration', status: 'REVIEW' },
    { title: 'October progress cut-off', meta: '92% data completeness · 6 missing records', status: 'OPEN' },
  ],
  engineering: [
    { title: 'Viaduct P47 crack assessment', meta: '4 drawings · 2 specifications · 1 NCR linked', status: 'ACTIVE' },
    { title: 'Station MEP interface conflict', meta: 'BIM clash cluster · 3 disciplines', status: 'REVIEW' },
    { title: 'RFI aging above 14 days', meta: '12 RFIs · 4 affect critical works', status: 'ACTION' },
  ],
  delivery: [
    { title: 'Long-lead switchgear exposure', meta: 'Supplier forecast +21 days · systems package', status: 'ACTION' },
    { title: 'Night shift productivity', meta: '78% of plan · constrained access window', status: 'WATCH' },
    { title: 'Track slab workfront readiness', meta: '5 of 6 prerequisites complete', status: 'READY' },
  ],
  commercial: [
    { title: 'Owner notice response window', meta: '32 hours remaining · evidence pack 84%', status: 'URGENT' },
    { title: 'Potential variation VO-027', meta: 'Design change · time and cost linked', status: 'REVIEW' },
    { title: 'Payment certificate No. 18', meta: '92% substantiated · 3 exceptions', status: 'OPEN' },
  ],
  assurance: [
    { title: 'Critical HSE corrective action', meta: 'Working at height · due today', status: 'URGENT' },
    { title: 'NCR recurrence cluster', meta: 'Concrete finishes · 6 related records', status: 'ACTION' },
    { title: 'Permit readiness', meta: '14 active · 2 expire within 30 days', status: 'WATCH' },
  ],
  resources: [
    { title: 'Systems competency coverage', meta: '94% qualified · 11 gaps', status: 'ACTION' },
    { title: 'Crane utilization imbalance', meta: 'Zone C at 91% · Zone A at 44%', status: 'REVIEW' },
    { title: 'Localized induction release', meta: 'EN / BM / 中文 · revision approved', status: 'READY' },
  ],
  knowledge: [
    { title: 'Contract evidence graph', meta: '1,284 nodes · 96% version traceability', status: 'LIVE' },
    { title: 'Lessons from pier defects', meta: '8 projects · 23 verified practices', status: 'READY' },
    { title: 'Unresolved terminology conflicts', meta: '4 defined terms across 3 languages', status: 'REVIEW' },
  ],
  assets: [
    { title: 'Handover data completeness', meta: '67% · 1,248 assets registered', status: 'ACTION' },
    { title: 'Commissioning test packs', meta: '82 of 116 ready for execution', status: 'OPEN' },
    { title: 'Maintainability review', meta: '14 findings · 9 closed', status: 'REVIEW' },
  ],
};

const ZH: Record<string, Scenario[]> = {
  project: [
    { title: '关键路径抢赶 · C4 标段', meta: '18 天偏差 · 3 个关联工作包', status: '行动' },
    { title: '完工预测超支敞口', meta: '+7600 万 · 由设计变更与赶工导致', status: '复核' },
    { title: '10 月进度截止数据', meta: '92% 数据完整度 · 缺失 6 项记录', status: '待处理' },
  ],
  engineering: [
    { title: 'P47 高架桥裂缝评估', meta: '4 份图纸 · 2 份规范 · 关联 1 项 NCR', status: '进行中' },
    { title: '车站机电接口冲突', meta: 'BIM 碰撞集群 · 涉及 3 个专业', status: '复核' },
    { title: '超期 14 天的技术问询（RFI）', meta: '12 项 RFI · 4 项影响关键工作', status: '行动' },
  ],
  delivery: [
    { title: '长周期开关柜交付风险', meta: '供应商预测延误 21 天 · 系统标段', status: '行动' },
    { title: '夜班生产率', meta: '完成计划的 78% · 受限于作业窗口', status: '关注' },
    { title: '轨道板工作面就绪度', meta: '6 项前置条件已完成 5 项', status: '就绪' },
  ],
  commercial: [
    { title: '业主通知响应窗口期', meta: '剩余 32 小时 · 证据包完成度 84%', status: '紧急' },
    { title: '潜在变更 VO-027', meta: '设计变更 · 关联工期与成本', status: '复核' },
    { title: '第 18 期付款证书', meta: '92% 已有证据支撑 · 3 项例外', status: '待处理' },
  ],
  assurance: [
    { title: '紧急 HSE 纠正措施', meta: '高处作业 · 今日到期', status: '紧急' },
    { title: '不符合项（NCR）复发集群', meta: '混凝土饰面 · 6 项关联记录', status: '行动' },
    { title: '许可证就绪情况', meta: '14 项有效 · 2 项将在 30 天内到期', status: '关注' },
  ],
  resources: [
    { title: '系统专业能力资质覆盖', meta: '94% 已取得资质 · 11 项缺口', status: '行动' },
    { title: '塔吊利用率失衡', meta: 'C 区 91% · A 区 44%', status: '复核' },
    { title: '本地化安全入场培训发布', meta: '英语 / 马来语 / 中文 · 修订版已批准', status: '就绪' },
  ],
  knowledge: [
    { title: '合同证据关系图', meta: '1,284 个节点 · 96% 版本可追溯率', status: '实时' },
    { title: '桥墩缺陷经验教训', meta: '8 个项目 · 23 项已验证做法', status: '就绪' },
    { title: '未解决的术语冲突', meta: '3 种语言中 4 个既定术语存在冲突', status: '复核' },
  ],
  assets: [
    { title: '移交数据完整度', meta: '67% · 已登记 1,248 项资产', status: '行动' },
    { title: '调试测试包', meta: '116 项中 82 项已具备执行条件', status: '待处理' },
    { title: '可维护性评审', meta: '14 项发现 · 已关闭 9 项', status: '复核' },
  ],
};

export function getScenarios(locale: string, slug: string): Scenario[] {
  const table = locale === 'zh' ? ZH : EN;
  return table[slug] || [];
}
