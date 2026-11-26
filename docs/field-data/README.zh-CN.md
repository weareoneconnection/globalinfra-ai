# 授权现场数据导入流程

这条流程把**经授权、已脱敏**的真实项目资料（往来函件、NCR、施工日报、变更申请等）导入知识库，用来支撑评分标准中"数据支撑"的"属地业务数据"。

**原则：没有书面授权的数据一律不导入；评委要能查到授权编号；代码仓库里永远不出现原始文件。**

## 1. 取得授权

1. 找有权处置这批资料的单位（项目业主或总承包商）出具书面授权，写明：
   - 用途
   - 资料范围（项目、文件类型、国家）
   - 有效期
   - 是否允许在比赛现场展示
2. 签字原件存档，**不要放进仓库**。
3. 复制 `AUTHORIZATION.template.json`，按授权书内容填写，`evidence_ref` 填授权书的存档编号。

## 2. 准备原始资料（放在仓库外）

- 把文件转成 `.txt` / `.md` / `.eml` / `.csv`，放在仓库以外的目录，例如 `~/secure/raw/ecrl-letters/`。
- `names.txt`：每行一个需要替换成 `[PERSON]` 的人名，包括签字人、收件人、现场人员。
- `aliases.json`：把真实的公司名、项目名、地名换成代号，例如：

```json
{"某某建设有限公司": "Contractor A", "Real Owner Berhad": "Owner B", "Station S12": "Station X"}
```

## 3. 运行脱敏

```bash
python scripts/field_data_intake.py --input ~/secure/raw/ecrl-letters --authorization ~/secure/raw/AUTHORIZATION.json --project-code <项目代码> --country MY --document-type CORRESPONDENCE --names ~/secure/raw/names.txt --aliases ~/secure/raw/aliases.json --out ~/secure/field_data
```

脚本在以下情况会直接拒绝运行：

- 没有授权文件，或授权字段不全
- 授权已过期
- 文件类型或国家超出授权范围
- 原始资料放在仓库内

脚本自动去除以下信息：

- 邮箱、电话（马来西亚、印尼、中国号码格式）
- 马来西亚身份证号、印尼 NIK、护照号、银行账号
- 带称谓的人名（Mr / Encik / Bapak 等）
- `names.txt` 和 `aliases.json` 中列出的名称

## 4. 人工复核（必做）

1. 看 `redaction_report.json`：各类信息被替换了多少处。报告只有计数，不含原值。
2. 抽查至少 10% 的记录，确认没有漏掉的人名、电话、合同金额等敏感信息。必要时补充 `names.txt` 或 `aliases.json` 后重跑。

## 5. 导入系统

启动 API 时设置 `FIELD_DATA_DIR=~/secure/field_data`。导入后的规则：

- 记录以 `FIELD_RECORD` 类型、`CONFIDENTIAL` 密级挂在对应项目下，只有该项目成员能检索到，不进入公开检索，也不影响 30 题公开评测。
- 授权过期后，下次启动会自动删除这些记录。

## 不要做的事

- 不要把原始资料、授权书原件或脱敏前的文件提交到仓库。
- 不要编造"真实案例"。评分标准要求"来源合规可靠"，答辩时评委一问授权来源，编造的数据会让整个数据项失分。
