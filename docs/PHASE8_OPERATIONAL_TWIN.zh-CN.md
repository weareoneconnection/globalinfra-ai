# 阶段 8：运营级数字孪生

GlobalInfra AI V4.0 将六格式模拟孪生包升级为可运行的运营级纵向闭环。每个项目使用同一组稳定 Twin ID 贯通几何、GIS、遥测、进度成本和 AI 引用。

| 阶段 | 可运行能力 | 入口 |
| --- | --- | --- |
| 8.1 | 原生 WebGL、GLTF 节点加载、对象拾取 | `/twin` |
| 8.2 | 模型版本、校验和、差异与转换任务 | `/twin/model-versions`、`/twin/conversions` |
| 8.3 | 一键生成项目、孪生图谱及六格式数据面 | `/twin/generate` |
| 8.4 | 时序入库、历史查询与 SSE 实时流 | `/twin/telemetry/*` |
| 8.5 | 4D 进度时间轴及 5D 健康/进度/成本着色 | WebGL 工作台 |
| 8.6 | 返回 Twin ID、事件、模型版本和时间戳引用的 Copilot | `/twin/copilot/query` |
| 8.7 | 由真实接口数据驱动的七步、180 秒演示 | `/showcase` |

## 接入边界

- 内置转换器是可执行的参考适配器；真实客户 IFC 批量转换仍需配置外部 Worker 与对象存储。
- 实时遥测通过 SSE 传输模拟或已写入的读数；生产 MQTT/BMS/SCADA Broker 属于外部连接器。
- Twin Copilot 在演示环境采用确定性证据推理，不自动执行项目或商务动作，所有回答均显示人工审批边界。
- 内置项目数据均标记为 `SYNTHETIC_DEMO`，不冒充竣工模型或客户数据。
