#!/usr/bin/env python3
"""P3.2 championship evidence pack compiler.

Consumes the existing public, synthetic-only /competition/finals/overview.
It DOES NOT invent award scores, customer ROI, model advantages, production
adoption or physical remediation. The produced pack is a REHEARSAL artifact,
never signed production proof. Real claims require separate approved releases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "globalinfra.p3-2.championship-pack.v1"
OVERVIEW = "globalinfra.finals-mission.v1"
SCORING = "C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS"
CRITERIA = [
    ("industry-pain", 10),
    ("technology-fusion", 8),
    ("business-model", 7),
    ("technical-route", 15),
    ("data-support", 10),
    ("report-quality", 8),
    ("scenario-fit", 7),
    ("scalability", 5),
    ("economic-impact", 8),
    ("overseas-promotion", 7),
    ("live-presentation", 15),
]
CHAPTERS = [
    ("00:00–00:35", "海外工程业务难题", "说明业主函件、风险识别和跨专业协同的真实行业需求"),
    ("00:35–01:20", "跨语种接入与属地资料", "展示多语言接入、来源索引，明确国家法规未获独立认证"),
    ("01:20–02:15", "专业 AI 协同", "展示六阶段任务、专家智能体与结构化证据，不能宣称实际模型胜出"),
    ("02:15–03:05", "人工授权与可信行动", "演示五主体审批、只生成草稿、签名校验和防篡改"),
    ("03:05–04:05", "技术证据与业务价值", "展示签名测试证明；如无审计数据则明确 NOT_RUN / 无已审核 ROI"),
    ("04:05–05:00", "跨国复制与决赛结论", "展示 MY/AE 配置不同、受治理推广路径，不冒充海外正式上线"),
]
QUESTIONS = [
    ("相比通用大模型创新在哪？",
     "本项目的核心创新在工程证据约束、属地适配、岗位责任分离与受治理执行，而非自研基础模型。"),
    ("多模型专家评估能说明你们最好吗？",
     "不能。AI 评审是内部自动筛查，真实优势需要冻结盲测、独立专业人工裁决与来源审计。"),
    ("已节省多少人工和成本？",
     "目前没有可以公开引用的已审核节时、成本或经济效益结果，采用配对试点协议采集证据。"),
    ("真实现场隐患已经解决了吗？",
     "没有。参赛黄金案例只完成合成函件草稿工作流；不代表现场整改或独立复检。"),
    ("马来西亚适用的法律条文已经验证了吗？",
     "国家包包含官方来源索引和许可关卡配置，仍需当地合格专家逐条复核，不能声称法律认证。"),
    ("能否去其他国家商业化？",
     "架构允许按国家与专业包适配，但尚未证明第二国家生产部署，需当地合作方、授权数据与真实试点。"),
    ("部署怎么证明是这次代码？",
     "验证 GitHub 受保护主分支的签名证据、Commit、镜像 Digest 与实际 Railway 运行版本一致。"),
    ("现场没有网络或模型服务怎么办？",
     "准备录屏与脱敏离线证据包，并明确预录内容和实时演示的边界，避免现场现场生成假数据。"),
]
ACCESS = [
    ("Mission Control", "/competition/finals", "公开合成演示主线"),
    ("Jury Control Room", "/competition/jury", "五主体受控审批和签名核验"),
    ("Evidence Center", "/competition", "11项指标及签名测试证据"),
    ("Overview JSON", "/competition/finals/overview?lang=zh", "只读公开模型，无租户原始 ROI"),
]


def canonical(o: object) -> bytes:
    return json.dumps(o, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(o: object) -> str:
    return hashlib.sha256(canonical(o)).hexdigest()


def _require(value: bool, code: str) -> None:
    if not value:
        raise ValueError(code)


def compile_pack(overview: dict, expected_commit: str) -> dict:
    """Fail closed on false boundaries, and never upgrade evidence to claims."""
    _require(isinstance(overview, dict), "OVERVIEW_REQUIRED")
    _require(overview.get("schema") == OVERVIEW, "OVERVIEW_SCHEMA_MISMATCH")
    _require(overview.get("scoring_standard") == SCORING, "RUBRIC_ID_MISMATCH")
    _require(overview.get("scenario", {}).get("synthetic") is True, "REAL_CASE_NOT_PUBLICLY_CLEARED")
    _require(overview["scenario"].get("data_boundary") == "SYNTHETIC_COMPETITION_ONLY",
             "PUBLIC_DATA_BOUNDARY_MISMATCH")
    mission = overview.get("mission", {})
    _require(mission.get("external_delivery_performed") is False, "EXTERNAL_DELIVERY_CLAIM_FORBIDDEN")
    _require(mission.get("project_safety_case_closed") is False, "PHYSICAL_CLOSURE_CLAIM_FORBIDDEN")
    _require(mission.get("physical_hazard") == "REINSPECTION_NOT_PERFORMED",
             "PHYSICAL_REINSPECTION_UNVERIFIED")
    _require(len(mission.get("steps", [])) == 6, "SIX_STAGE_STORY_MISMATCH")
    impact = overview.get("business_impact", {})
    model = impact.get("model_comparison", {})
    roi = impact.get("paired_roi", {})
    _require(model.get("status") == "NOT_RUN" and model.get("verified_score") is None,
             "REAL_MODEL_RESULT_MUST_USE_SEPARATE_APPROVED_EVIDENCE")
    _require(roi.get("status") == "NO_AUDITED_PUBLIC_RESULT"
             and roi.get("improvement_percent") is None
             and roi.get("baseline_minutes") is None
             and roi.get("assisted_minutes") is None,
             "PUBLIC_ROI_CLAIM_MUST_HAVE_SEPARATE_APPROVED_EVIDENCE")
    _require(overview.get("country_adaptation", {}).get("status") == "CONFIGURATION_COMPARISON_ONLY",
             "COUNTRY_LAW_CERTIFICATION_NOT_ESTABLISHED")
    scorecard = overview.get("scorecard", [])
    _require(isinstance(scorecard, list) and len(scorecard) == 11, "ELEVEN_CRITERIA_REQUIRED")
    pairs = [(x.get("id"), x.get("max_score")) for x in scorecard]
    _require(pairs == CRITERIA and sum(x["max_score"] for x in scorecard) == 100,
             "OFFICIAL_SCORE_WEIGHTS_MISMATCH")
    _require(len(expected_commit) == 40
             and all(c in "0123456789abcdef" for c in expected_commit.lower()),
             "EXACT_FORTY_HEX_COMMIT_REQUIRED")

    release = overview.get("release", {})
    verified = release.get("status") == "VERIFIED_PASSED"
    observed_commit = release.get("commit", "")
    # The public API returns the first 12 hex chars of deployment commit.
    commit_match = (isinstance(observed_commit, str)
                    and observed_commit.lower() == expected_commit[:12].lower())
    code_released = verified and commit_match
    result = {
        "schema": SCHEMA,
        "status": "REHEARSAL_PACK_ONLY",
        "publication_gate": "CLOSED_PENDING_INDEPENDENT_SOURCE_AUDIT",
        "source_overview_sha256": sha256(overview),
        "expected_commit": expected_commit,
        "release": {
            "status": release.get("status", "UNVERIFIED"),
            "commit_prefix": observed_commit if isinstance(observed_commit, str) else "INVALID",
            "passed_cases": release.get("verified_cases") if code_released else None,
            "total_cases": release.get("total_cases") if code_released else None,
            "signed_release_matches_commit": code_released,
            "outcome": ("SIGNED_CODE_EVIDENCE_MATCHED_NOT_LIVE_BROWSER_VERIFIED"
                        if code_released else "RELEASE_NOT_VERIFIED_FOR_THIS_COMMIT"),
            "signed_release_does_not_prove_business_impact": True,
        },
        "scenario": {
            "id": overview["scenario"].get("id"),
            "country": overview["scenario"].get("country_code"),
            "synthetic": True,
            "document_workflow": mission.get("document_workflow", "NOT_VERIFIED"),
            "physical_hazard": "REINSPECTION_NOT_PERFORMED",
            "external_delivery": "NOT_SENT",
        },
        "scorecard": [
            {
                "id": row["id"], "criterion": row["criterion"],
                "max_score": row["max_score"],
                "evidence_ids": row.get("evidence_ids", []),
                "awarded_score": None,
            } for row in scorecard
        ],
        "capabilities": {
            "AI_GOAL_AND_MULTIAGENT_WORKFLOW": "CODE_AND_SYNTHETIC_DEMO",
            "SIGNED_GOVERNANCE": "CODE_AND_SIGNED_CI_ONLY",
            "MODEL_SUPERIORITY": "NOT_RUN",
            "EXPERT_INDEPENDENCE": "NO_AUDITED_HUMAN_ATTESTATION",
            "REAL_FIELD_ROI": "NO_AUDITED_PUBLIC_RESULT",
            "MY_AE_ADAPTATION": "CONFIGURATION_COMPARISON_ONLY",
            "MULTICOUNTRY_PRODUCTION": "NOT_VERIFIED",
            "LIVE_DEMO_VISUAL_QA": "NOT_VERIFIED_BY_THIS_PACK",
        },
        "demo_routes": [{"name": n, "path": p, "scope": s} for n, p, s in ACCESS],
        "five_minute_script": [{"time": time, "title": title, "talk_track": text}
                               for time, title, text in CHAPTERS],
        "jury_questions": [{"question": q, "answer": a} for q, a in QUESTIONS],
        "must_verify_before_stage": [
            "审核冻结演示版本与 deployed Commit / API signed-evidence 一致",
            "实际浏览器核对中英文页面、交互、投屏比例和网速",
            "五主体完整操作一次，检查403无副作用和回执防篡改",
            "录制严格标注的脱机备份；现场无需读取真实客户信息",
            "更新国家包合规审核状态，不能只引用来源索引",
            "真实模型及 ROI 主张必须取得单独人审证据与公开许可",
            "确认组委会真实终评时长、设备、现场网络和提交物要求",
        ],
        "risks": [
            "宣传稿不可把权重 100 解释为获得 100 分",
            "合成沙箱完成不等于现场整改或项目已商业上线",
            "跨模型自动评价不是独立人类专家评估",
            "没有独立盲测和工时原始记录时，不承诺提升百分比",
        ],
    }
    return result


def markdown(pack: dict) -> str:
    lines = [
        "# GlobalInfra AI — P3.2 特等奖终评演示手册",
        "",
        f"- 代码基线：\`{pack['expected_commit']}\`",
        f"- 签名代码证据：\`{pack['release']['outcome']}\`",
        "- 适用：终评彩排与提交前内部审核；**不是已经核验真实商业价值的证明**",
        "",
        "## 五分钟主讲脚本（供彩排；最终时长以组委会通知为准）",
        "",
    ]
    for item in pack["five_minute_script"]:
        lines.extend([f"### {item['time']} · {item['title']}",
                      item["talk_track"], ""])
    lines.extend(["## 现场演示入口", ""])
    for item in pack["demo_routes"]:
        lines.append(f"- **{item['name']}**：\`{item['path']}\` — {item['scope']}")
    lines.extend(["", "## 官方11项评分：权重不是获奖分数", ""])
    for item in pack["scorecard"]:
        lines.append(f"- {item['criterion']}（权重{item['max_score']}）"
                     f" · 证据ID：{', '.join(item['evidence_ids'])}")
    lines.extend(["", "## 8 个终评常见追问", ""])
    for item in pack["jury_questions"]:
        lines.extend([f"**{item['question']}**", "", item["answer"], ""])
    lines.extend(["## 上台前冻结清单", ""])
    for item in pack["must_verify_before_stage"]:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "## 公开证据边界", "",
                  f"- 模型优势：\`{pack['capabilities']['MODEL_SUPERIORITY']}\`",
                  f"- 经济效益：\`{pack['capabilities']['REAL_FIELD_ROI']}\`",
                  f"- 海外推广：\`{pack['capabilities']['MULTICOUNTRY_PRODUCTION']}\`",
                  f"- 报告状态：\`{pack['status']}\` · \`{pack['publication_gate']}\`",
                  "",
                  "所有当前指标均为工程测试或合成演示，不替代真实工程专业复核。",
                  ""])
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--overview", type=Path, required=True)
    p.add_argument("--commit", required=True, help="Exact 40-character deployed git commit")
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    try:
        overview = json.loads(args.overview.read_text(encoding="utf-8"))
        packet = compile_pack(overview, args.commit)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "championship-pack.json").write_text(
            json.dumps(packet, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (args.output_dir / "championship-rehearsal.md").write_text(
            markdown(packet), encoding="utf-8",
        )
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "FAILED_CLOSED",
            "error_type": type(exc).__name__,
            "publication_gate": "CLOSED",
        }))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
