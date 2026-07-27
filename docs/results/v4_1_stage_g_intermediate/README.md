# V4.1 Stage G 中间交付汇总

本目录只保存 Stage G 的聚合结论，不保存逐视频输出、标注、sealed/held-out
逐样本语义、视频或模型权重。

本轮固定运行完成 110/110 个视频，运行时失败为 0，链路完整性验证通过；但官方
Stage G 质量门失败。当前模型只能作为 `intermediate_development_model` 使用，
不能表述为 final、full-data、independent-test-passed 或 production-approved。

冻结 scorer 对中文权威 CSV 的部分列名未建立映射，因此时间、机制、位置和特殊样例
分母为 0。该缺陷不允许事后修改本轮官方门禁，也不能把未计算的字段解释为通过。
存在性指标本身同样低于阈值，故失败结论不依赖上述覆盖缺陷。

