# TensileAgent 项目对齐报告（revision 2）

## 范围
- 源码版本：main @ 4467174（dirty）
- revision 2 新增：backlog 9 项全部完成 L2 深挖，功能覆盖 16/16

## Confirmed Gap（累计 6）
1. GAP-DEL-CONFIRM / 2. GAP-WEB-CONCURRENCY / 3. GAP-BATCH-VISIBILITY（revision 1）
4. GAP-MOCK-POLLUTION（CAND-003）：mock 结果污染正式结果集无标识
5. GAP-EXPORT-ERROR（CAND-007）：json/jsonl 导出丢失失败详情
6. GAP-UNRECOGNIZED-SEMANTICS（CAND-001）：两类无法识别同词两义

## Suspected Risk（累计 4）
- GAP-QG-FUTURE（revision 1）；GAP-SETUP-ENV-PERMS、GAP-SETUP-CONFIG-REWRITE（CAND-010）；GAP-BUNDLE-OVERWRITE（CAND-016）

## 对齐良好
- CAND-002 批量失败不阻断 + 落盘后 exit 1；CAND-009 双层脱敏；CAND-016 V2 准入与写一次；CAND-011 doctor fail-closed

## 残余限制
- CLI main 级集成测试缺失（CAND-001 testValidity partial）；外部视觉服务能力在兄弟仓库未分析；本分析为 best-effort
