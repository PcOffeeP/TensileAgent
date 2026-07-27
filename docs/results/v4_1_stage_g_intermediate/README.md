# V4.1 Stage G 中间交付汇总

本目录只保存 Stage G 的聚合结论，不保存逐视频输出、标注、sealed/held-out
逐样本语义、视频或模型权重。

本轮固定运行完成 110/110 个视频，运行时失败为 0，链路完整性验证通过。当前中间
交付只把身份、产物完整性、测试、服务、真实调用和 fail-closed 作为门禁；性能指标
只记录最新快照，不比较阈值、不阻断交付、不触发优化或重训。

历史 Stage G 质量门失败事实仍保留。当前模型只能作为
`intermediate_development_model` 使用，不能表述为 final、full-data、
independent-test-passed 或 production-approved。

冻结 scorer 对中文权威 CSV 的部分列名未建立映射，因此时间、机制、位置和特殊样例
分母为 0。该缺陷不允许事后修改本轮官方门禁，也不能把未计算的字段解释为通过。
存在性指标按原始测量值记录，见 `performance_snapshot.json`；当前处置为“暂定、
不优化”，不把这些数值转换成新的通过/失败门。
