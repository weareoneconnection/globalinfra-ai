# Drawing-to-Twin P0～P2 决赛说明

> English summary: GlobalInfra AI turns evidence-bearing engineering drawings into traceable **draft** 3D/IFC artifacts. It does not claim CAD-authoring parity, design-code compliance, or construction approval. Every generated artifact is marked `AI_GENERATED_DRAFT / NOT_FOR_CONSTRUCTION`.

## 一句话价值

工程师上传图纸后，系统把“看图、找证据、确认不确定项、生成草模、导出审查件”串成一条可复核链路：每个可用事实都回到原始文件的 SHA-256、页码和归一化坐标框；缺少比例、单位、层高、墙厚或已确认几何时，模型生成失败关闭。

这项能力的定位是**设计审查与数字孪生建模的可信起点**，不是替代 CAD/BIM 设计人员，也不是自动发布施工模型。

## P0～P2 交付边界

| 阶段 | 已实现的可验证能力 | 明确不声称 |
| --- | --- | --- |
| P0 · Drawing Intelligence | 校验 PDF/PNG/JPEG/TIFF 文件签名；保留原件及内容摘要；确定性解析带文字层/矢量内容的 PDF；输出页码、坐标框、置信度和来源文本；证据化问答只返回已提取事实；人工确认有审计状态 | 不把文件名、像素尺寸或模型常识当作图纸事实；未取得可验证视觉结果的栅格图保持 `OCR_REQUIRED` |
| P1 · Constrained 3D | 仅把通过门禁的确认几何转换为带真实 mesh/accessor 的 glTF；稳定 Twin ID；产物摘要和来源证据写入 manifest | 不承诺从任意复杂施工图自动恢复完整拓扑、机电连接、碰撞关系或设计意图 |
| P2 · Draft BIM | 生成 IFC4X3 Draft 审查件；建立项目/场地/建筑/楼层空间层级；携带 IFC GUID、Twin ID、来源证据与 `NOT_FOR_CONSTRUCTION` 边界 | 不宣称完整 BIM authoring、规范合规、LOD/LOI 认证、可施工性或自动发布到运营孪生 |

视觉模型接入点支持受约束的内联图像与结构化输出。部署未配置可用视觉模型，或视觉输出无法通过 schema、坐标和证据校验时，栅格/扫描件不得进入建模门禁，状态继续为 `OCR_REQUIRED`。`restricted` 数据只能按平台的本地模型路由规则处理。

## 可信链路

```text
原始图纸
  └─ 文件签名 + 大小限制 + SHA-256
       └─ 页级解析（文字 / 矢量 / 受约束视觉接入点）
            └─ 结构化事实 + page/bbox/source evidence
                 ├─ 证据化问答：有引用才回答，无证据则拒答
                 └─ 工程师确认：单位 / 比例 / 参数 / 几何
                      └─ fail-closed model gate
                           ├─ glTF Draft + digest
                           └─ IFC4X3 Draft + digest
                                └─ manifest + validation + ingestion receipt
```

五个不可绕过的生成条件：

1. 单位由工程师确认；
2. 比例由工程师确认；
3. 层高由工程师确认；
4. 墙厚由工程师确认；
5. 至少一个带页码、坐标框和源文件摘要的几何输入由工程师确认。

若来源是 PNG/JPEG/TIFF，另须由工程师确认米/像素校准值；图纸比例不能替代扫描分辨率校准。

任何一个条件缺失时，`POST /drawings/{drawing_id}/model` 返回门禁错误；`publish: true` 始终被拒绝。成功生成也只表示产物通过内部结构与追溯检查，不代表工程设计通过审核。

## 关键接口

| 方法与路径 | 用途 | 关键证据/边界 |
| --- | --- | --- |
| `POST /drawings/analyze` | 上传并解析图纸 | 原件 SHA-256、页级状态、接入回执、数据分级 |
| `GET /drawings/{id}` | 查看图纸、构件、门禁状态 | `page + bbox + source_sha256 + confidence + review state` |
| `GET /drawings/{id}/source` | 获取受权限保护的原件 | `private, no-store` |
| `GET /drawings/{id}/pages/{page}/preview` | 获取带坐标基准的页预览 | `private, no-store` |
| `POST /drawings/{id}/ask` | 在已提取事实内问答 | 每个回答事实必须带引用；无证据时 `grounded: false` |
| `POST /drawings/{id}/confirm` | 工程师确认事实与建模参数 | `USER_CONFIRMED`、确认人、确认值 |
| `POST /drawings/{id}/model` | 原子生成 glTF + IFC Draft 证据包 | 禁止发布；不接受缺少任一格式的半包；manifest、validation、digest、receipt |
| `GET /drawings/{id}/models/{run_id}/gltf` | 下载 3D 草模 | `X-Data-Provenance: AI_GENERATED_DRAFT_NOT_FOR_CONSTRUCTION` |
| `GET /drawings/{id}/models/{run_id}/ifc` | 下载 IFC4X3 草模 | 同上，且 IFC 内嵌非施工用途声明 |

Web 工作台入口为 `/drawings`。

## 安全、隔离与追溯

- 图纸、页预览和模型产物继承组织与项目范围；跨组织或越权项目请求返回 `404`，不泄露资源是否存在。
- `internal` 与 `restricted` 图纸必须绑定项目；只有明确的 `public` 数据可以不绑定项目。
- 原始图纸、glTF 与 IFC 使用 `private, no-store`；下载响应禁止 MIME 嗅探。
- 接入回执记录源文件摘要、解析器版本、上传人、项目、数据分级和门禁结果。
- 模型 manifest 记录源图 SHA-256、Twin ID、IFC GUID、构件证据、派生规则与产物摘要。
- 派生几何必须声明 `derived_from`；验证口径是“输入已确认、派生可追溯”，不得把派生构件表述成逐件人工确认。
- 生成记录只进入隔离的 `DrawingModelRun(status=DRAFT_GENERATED)`；不会创建正式 `TwinModelVersion`。本能力没有外部发布、施工审批或运营孪生自动替换权限。

## 五分钟决赛演示

| 时间 | 操作 | 评委看到的证明 |
| --- | --- | --- |
| 0:00–0:35 | 打开 `/drawings`，上传一张带文字层和矢量房间轮廓的合成 PDF | 文件摘要、页数、图号/版本/比例/单位、解析状态 |
| 0:35–1:20 | 点击一个构件，定位原图坐标框；询问“图号和房间尺寸是什么？” | 回答中的页码、坐标框、来源文本和置信度 |
| 1:20–1:45 | 询问图中不存在的“施工批准人是谁？” | `grounded: false`，系统明确拒绝推断 |
| 1:45–2:15 | 在未确认参数时尝试生成 | 门禁列出未确认比例/单位/层高/墙厚/几何，生成失败关闭 |
| 2:15–3:00 | 由工程师核对并确认参数和一个矢量几何 | `USER_CONFIRMED`、确认值、模型门禁转为 `READY` |
| 3:00–4:05 | 生成 glTF 与 IFC Draft，并在 3D 视图查看 | 可交互 mesh、Twin ID、IFC GUID、证据锚点、validation |
| 4:05–4:35 | 下载 IFC 与 glTF，展示摘要和非施工标识 | 两个 artifact digest、`NOT_FOR_CONSTRUCTION`、私有缓存策略 |
| 4:35–5:00 | 总结可信边界 | “AI 提取 + 人确认 + 可追溯派生”，不是自动施工设计 |

演示数据必须使用公开或合成图纸。若现场视觉模型不可用，就用带文字层/矢量的确定性 fixture 完成主线，并现场展示一张栅格图保持 `OCR_REQUIRED`；不得口头把未运行能力说成已通过。

## 可复现验收矩阵

| 验收项 | 正向证明 | 负向证明 | 自动化证据 |
| --- | --- | --- | --- |
| 文件接入 | 合法 PDF/PNG 被保留并生成 SHA-256 | 空文件、超限或伪造签名被拒绝 | `test_drawings.py` |
| 坐标级证据 | 元素带归一化 bbox、页码和源摘要 | 不支持的问题返回无引用拒答 | `test_pdf_analysis_returns_exact_evidence_and_grounded_answer` |
| 栅格失败关闭 | 有合规视觉结果时可形成候选事实；校准后才可建模 | 无视觉/OCR 证据时保持 `OCR_REQUIRED` 且不造元素 | `test_configured_vision_extracts_reviewable_raster_evidence`、`test_raster_drawing_is_retained_but_never_invented_without_ocr`、`test_llm_vision.py` |
| 人工门禁 | 所有必要输入确认后转为 `READY` | 任一必要输入缺失时禁止生成 | `test_source_preview_and_human_model_gate_are_private_and_fail_closed` |
| 3D/IFC Draft | glTF 有 mesh/accessor；IFC 声明 IFC4X3；摘要一致 | `publish: true` 被拒绝；未确认元素不进入模型 | `test_drawing_model_engine.py`、模型 API 端到端测试 |
| 可追溯派生 | 构件携带源证据；派生墙回指确认轮廓 | 不允许把派生墙伪称逐件人工确认 | engine manifest/validation assertions |
| 租户隔离 | 同组织、授权项目可读取 | 跨组织/跨项目访问返回 `404` | drawing isolation tests |
| 数据边界 | restricted 数据按本地路由处理 | 不可用或非法视觉输出不回退到虚构答案 | `test_generate_vision_has_no_fabricated_mock_fallback` |

候选 commit 上执行：

```bash
cd services/api
.venv/bin/python -m pytest \
  tests/test_drawings.py \
  tests/test_drawing_model_engine.py \
  tests/test_llm_vision.py -q

cd ../../apps/web
npm run lint
npx tsc --noEmit
npm run build
```

以上通过只能证明固定测试与构建可复现；它不等于真实项目识别准确率、规范审查结论或生产发布证明。真实项目应另行使用获授权的图纸集，按专业、图纸类型、扫描质量和版本分层报告准确率、拒答率、人工修正率、耗时与失败分布。

## 评委问答口径

**能不能读图纸？**  能。文字层和矢量 PDF 走确定性解析；图像/扫描件必须经过已配置的视觉/OCR 路径并通过结构化证据校验，否则明确停在 `OCR_REQUIRED`。

**能不能直接生成 3D？**  能生成受约束的 glTF Draft，但必须先确认比例、单位、关键参数和几何。复杂构造、专业系统拓扑和设计意图不会凭空补齐。

**能不能生成 BIM？**  能生成带 IFC4X3 结构、稳定 ID 和来源证据的 Draft BIM 审查件；它不是可直接施工的完整 BIM，也不替代专业复核。

**为什么这比普通“看图 AI”更可信？**  因为每个可用事实都有源文件摘要、页码与坐标框；没有证据就拒答，缺确认就不建模，生成物也永久携带 Draft 边界和可验证摘要。

**下一阶段如何成为生产能力？**  接入经批准的 OCR/VLM 与对象存储，增加 DWG/DXF/原生 IFC 解析、跨图纸对齐、构件关系与 MEP 拓扑、专业规范校核、人工审签流程，以及真实项目分层评测；在这些工作完成前不提升当前能力声明。
