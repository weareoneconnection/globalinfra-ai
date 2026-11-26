# GlobalInfra AI V6.1 决赛运行手册

本文用于决赛现场的五分钟可复核演示。它规定演示顺序、证据口径和故障降级方式，不把演示环境描述成生产认证。

## 冠军叙事

一句话：GlobalInfra AI 不替人拍板；它把跨国工程风险变成“可追溯建议 → 两人审批 → 受控执行 → 独立核验 → 第五主体关闭”的签名行动链，并主动证明越权和篡改都会失败。

评委入口：`/competition/jury`。证据中心：`/competition`。

现场只讲三件事：

1. 业务价值：P47 高处作业风险被定位到项目、国家、Twin ID、期限和证据；
2. 治理差异：五个主体显式交接，AI 无审批权，外部发送始终为 `DRAFT_ONLY_NOT_SENT`；
3. 可验证性：越权请求返回 `403 ROLE_SCOPE_REQUIRED` 且状态摘要不变，篡改签名字段的内存副本返回 `INVALID_SIGNATURE`，数据库中的正式闭环仍为 `VERIFIED_INTACT`。

## 五分钟脚本

| 时间 | 操作 | 解说重点 | 屏上证据 |
| --- | --- | --- | --- |
| 0:00–0:25 | 打开 Jury Control Room | 一条马来西亚业主来函进入 P47 数字主线 | 国家、项目、Twin ID、24 小时期限、引用来源 |
| 0:25–0:45 | `开始评委验证` | 每位评委获得全新合成会话；票据只保存在浏览器内存 | 新 session ID、`SYNTHETIC_COMPETITION_ONLY` |
| 0:45–1:20 | 以 PM 身份执行 AI 分析 | AI 形成建议与审批要求，不获得行动权 | `AWAITING_APPROVAL`、PM/HSE 两个待审批项 |
| 1:20–1:45 | 运行越权挑战 | PM 尝试执行，服务端拒绝；随后重读状态并比较业务指纹 | `403 · ROLE_SCOPE_REQUIRED · STATE UNCHANGED` |
| 1:45–2:25 | PM 审批、HSE 会签 | 两个不同主体，不能由同一身份代批 | 两条具名审批与签名摘要 |
| 2:25–3:05 | 文控执行 | 只生成草稿，不发送给外部系统 | execution receipt、artifact digest、`DRAFT_ONLY_NOT_SENT` |
| 3:05–3:35 | 独立核验 | 核验人不能是执行人，检查审批、输入、产物和证据引用 | verification receipt、`VERIFIED` |
| 3:35–4:00 | 第五主体关闭 | 关闭人与前四个职责分开，形成终态 | closure digest、`CLOSED` |
| 4:00–4:25 | 运行篡改挑战 | 只改内存副本的 `execution.executor`；正式记录不变 | `INVALID_SIGNATURE · CANONICAL EVIDENCE UNCHANGED` |
| 4:25–5:00 | 停在闭环证据卡 | 总结五主体、双审批、三类回执、无外发和真实发布状态 | session、耗时、摘要、release evidence 状态 |

每一步必须点击对应的角色按钮。不要自动推进，也不要口头把 `UNVERIFIED` 解释成“已验证”。如果页面显示 `UNVERIFIED`，正确说法是：“业务闭环可现场复现；当前部署没有与本 commit 匹配的受保护签名发布证据，因此系统失败关闭。”

## 上场前检查

在候选 commit 上执行：

```bash
cd services/api
.venv/bin/python -m pytest tests -q
cd ../../apps/web
npm run lint
npx tsc --noEmit
npm run build
```

部署后保留以下输出或截图：

```bash
curl -fsS https://<web-domain>/healthz
curl -fsS https://<web-domain>/readyz
curl -fsS https://<api-domain>/health
curl -fsS https://<api-domain>/readyz
curl -fsS https://<api-domain>/competition/submission-evidence?lang=zh
```

还必须完成：

- 1440×900 浏览器下页面无整体滚动、按钮无裁切；
- 中英文各完整跑一次，刷新后明确创建新会话；
- 连续十次在 4 分 30 秒至 4 分 50 秒完成；
- 证据状态、部署 commit、镜像 digest 与 release manifest 一致；
- 演示机关闭通知、自动更新和密码弹窗，预先打开一个只读证据 API 标签页；
- 保留一个已验证的上一版本入口，但不得把它冒充为当前 V6.1。

## 部署后热身（决赛页展示真实闭环）

竞赛演示使用临时存储，每次重新部署后 `/competition/finals` 没有已完成的评委会话，六阶段任务链会显示待执行状态。部署完成后运行一次热身脚本，它按评委的方式走完五主体闭环（PM 分析与审批、HSE 会签、文控执行、独立核验、关闭），不伪造票据、不跳步：

```bash
python scripts/finals_warmup.py https://<web-domain>
```

脚本最后打印决赛页当前展示的会话 ID 与六个阶段状态。决赛页只展示**签名闭环仍然完整**的最近一次评委会话，并标明会话号、关闭时间、独立主体数和闭环摘要；没有完成的会话时如实显示待执行。

## 评委沙箱的模型路由

评委沙箱分析默认 `COMPETITION_MODEL_ROUTE=mock`，保证决赛主线完全确定。若要让评委看到真实大模型生成的专业结论，在 API 服务设置 `LLM_MODE=auto`、配置模型提供方，并设置 `COMPETITION_MODEL_ROUTE=auto`。工单类型、风险等级和双人审批要求在会话创建时就已固定，模型只影响智能体结论，不影响治理路径；模型失败时逐步回退到规则。切换后必须完整彩排至少三次再上场。

## 不可变发布晋级

V6.1 只有在以下链条完整时才可称为“已晋级发布”：

1. 默认分支的 API、Web 与 Compose smoke gates 全部通过；
2. 受保护 `release-signing` 环境批准 Ed25519 签名证据；
3. release job 对签名、commit、数据集和所有门禁执行失败关闭验证；
4. `Dockerfile.release` 在构建时验证内置证据 SHA-256，并以非 root 用户运行；
5. GitHub 为镜像摘要生成 build provenance；
6. `globalinfra.release-manifest.v1` 将 commit、证据 SHA-256、CI run 与 `ghcr.io/...@sha256:...` 绑定；
7. Railway 只按 manifest 中的 digest 晋级，不按可变 tag 或源码自动部署；
8. 运行时公钥、commit 和只读证据文件与 manifest 相符，`/readyz` 与证据 API 通过。

## 故障降级

- 创建会话失败：刷新一次后重新创建；不要复用或手工构造票据。
- 某一步超时：使用“重置”创建全新 session；旧 session 进入终止状态。
- 全屏失败：保持普通浏览器窗口，Jury 页面本身仍固定覆盖应用外壳。
- API 暂时不可用：停止点击，切到预先打开的只读证据 API 和 release manifest，明确说明这是静态证明，不伪造现场成功。
- 发布证据为 `UNVERIFIED`：保留原状态并解释缺少哪一项；不得改色、隐藏或口头升级为通过。
- 倒计时归零：页面不自动执行任何动作；由演示者停止并说明未完成步骤。

## 禁止口径

- 不说“AI 自动审批”“AI 自动发送”或“零人工”；
- 不把合成 fixture、mock AI 或固定回归称为真实项目准确率；
- 不展示完整角色票据、API key、OIDC token、签名私钥或客户数据；
- 不把 GitHub artifact、网页 URL 或截图单独当成发布证明；
- 不把控制已实现等同于生产依赖已配置或外部认证已取得。
