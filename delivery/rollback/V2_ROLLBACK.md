# V2 回滚边界

V2 仅作为显式回滚对象保留，不与 V4.1 在同一任务内自动混用。

回滚时必须：

1. 停止接收新任务并等待当前 V4.1 任务结束；
2. 保存当前 V4.1 deployment identity、配置和运行证据；
3. 显式切换到已冻结的 V2 deployment 与 V2 Agent 配置；
4. 运行 V2 contract/doctor 和真实媒体 smoke；
5. 新任务只接受 V2 contract，任何 V4.1 响应都 fail closed。

本中间交付没有执行新的 V2 同源长批处理，也不声称 V2 比较门已通过。

