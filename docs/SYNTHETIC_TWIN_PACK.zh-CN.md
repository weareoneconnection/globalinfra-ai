# 项目级合成数字孪生数据包

GlobalInfra AI 在没有客户真实项目接入时，为三个演示项目生成可下载、可追溯的合成数字孪生数据。每套数据包均由同一组稳定 `Twin ID` 生成，覆盖：

- IFC 4.3 STEP 模型；
- glTF 2.0 场景与节点元数据；
- 3D Tiles 1.1 tileset；
- GeoJSON 线路与资产要素；
- WMS 1.3.0 GetCapabilities 与 GetMap；
- IoT 遥测主题与实时读数。

入口为 `/twin?project_id=1|2|3`。清单接口为 `GET /twin/demo-pack/{project_id}/manifest`，其余资源地址由清单返回。静态资产带 SHA-256 摘要；所有响应和 UI 都标记 `SYNTHETIC_DEMO`。

这些资产用于比赛演示、集成开发、验收和销售沙盘，可以证明 IFC/GIS/三维/遥测到 Twin ID、工程事件、4D/5D、调试和运维的链路已经贯通。它们不是客户模型、实测数据或竣工模型，不得用于实际设计、施工或运营决策。

接入真实项目时，保留 API 和 Twin ID 契约，替换以下边界即可：

1. BIM/CDE 转换与对象存储；
2. GIS/瓦片/WMS 服务；
3. MQTT、BMS 或 SCADA 流；
4. 项目级坐标转换和对象映射；
5. 客户 OIDC、RBAC 与数据驻留策略。
