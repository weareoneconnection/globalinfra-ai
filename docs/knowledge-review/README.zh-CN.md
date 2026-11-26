# 条款库与术语表：专家审核流程

条款库（马来西亚 152 条、印尼 35 条）和术语表（马来语 231 条、印尼语 151 条）目前都标记为“待审核”（`EXPERT_REVIEW_REQUIRED` / `NATIVE_REVIEW_REQUIRED`）。**只有真实审核人填写并签字的审核包，才能改变这些标记。** 不得代填，也不得默认填写“准确”。

## 1. 请谁审

| 对象 | 合适的审核人 |
| --- | --- |
| 马来西亚条款 | 马来西亚执业律师（Advocate & Solicitor），或熟悉 OSHA、CIPAA 的属地合规负责人 |
| 印尼条款 | 印尼律师，或持 K3/SMKK 资格的属地安全经理 |
| 马来语、印尼语术语 | 母语工程师或专业译员 |

审核记录中只写审核人的**角色、资质和机构类型**。姓名须经本人书面同意才写入（`--reviewer-name`）。

## 2. 生成审核包

```bash
python scripts/build_review_packet.py --country MY --kind clause --per-instrument 5 --out ~/review/MY-clauses.csv
python scripts/build_review_packet.py --country ID --kind term --sample 60 --out ~/review/ID-terms.csv
```

审核包按法规（条款）或领域（术语）分层抽样。抽样以包编号为种子，可以复现。每行附有官方链接和读取来源。

## 3. 审核人填写

每行的 `verdict` 填三者之一：

- `ACCURATE`：准确。
- `MINOR_CORRECTION`：基本正确，需小改。`correction` 或 `comment` 必填。
- `INACCURATE`：错误。`comment` 必填。该条会从默认检索中撤下，修正后需重审。

另附一页封面，写明审核日期、审核范围和签字。原件保存在仓库之外，`--evidence-ref` 只记录存放位置。

## 4. 导入

```bash
python scripts/import_review.py --packet ~/review/MY-clauses.csv \
  --reviewer-role "Construction lawyer" --reviewer-qualification "Advocate & Solicitor, High Court of Malaya" \
  --reviewer-organisation-type "Law firm" --reviewed-on 2026-12-01 --evidence-ref "签字封面，存于……"
```

导入脚本会拒绝以下情况：

- 编号不在库中；
- 非 `ACCURATE` 却没有说明；
- 审核日期在未来；
- 一个文件里混有多个审核包。

未填写的行会跳过，并在输出中报告数量。

导入后，重启 API，`GET /knowledge/library` 的 `reviews` 字段会显示已审核数量和结论分布。对评委可以如实说明：“已由某类资质人员抽审 N 条，准确率 X%”。

## 5. 不要做的事

- 不要自己代填审核结论，也不要把“团队自查”写成“专家审核”。
- 不要在没有审核人同意的情况下写入姓名或联系方式。
- 抽审结果不代表全库都已审核：页面和演示中请说明“抽审”及样本量。
