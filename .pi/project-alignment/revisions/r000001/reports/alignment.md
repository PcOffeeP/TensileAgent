# TensileAgent 项目对齐报告

## 范围
- 源码版本：main @ 4467174（dirty：README.md 修改 + 2 个未跟踪 docs）
- 功能发现 16 项，L2 深挖 7 项，未深挖 backlog 9 项（CAND-001/002/003/007/009/010/011/012/016），覆盖度 partial

## 确认的缺口（Confirmed Gap）
1. GAP-DEL-CONFIRM（CAND-006）：删除无二次确认、错误静默，与用户预期冲突
2. GAP-WEB-CONCURRENCY（CAND-004）：单 worker 串行，与用户并发预期冲突
3. GAP-BATCH-VISIBILITY（CAND-005）：批量无批次标识与界面可见性，与用户预期冲突

## Suspected Risk
- GAP-QG-FUTURE（CAND-014）：本轮验收治理语义为流程/文档层，用户接受本轮现状，但要求未来新一轮验证必须代码层强制

## 对齐良好
- CAND-008 模型切换门禁（后端强制 + 测试覆盖）
- CAND-013 批处理恢复语义（成功不可覆盖、原子写）
- CAND-014 finalize 写一次强制
- CAND-015 LOCKED80 标记强制

## 限制
- 本分析为 best-effort；外部视觉服务能力在兄弟仓库，未分析；backlog 9 项未经 L2 审查；清单完整性受静态入口扫描限制（inventoryConfidence=low）
