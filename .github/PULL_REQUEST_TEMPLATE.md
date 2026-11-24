## 一句话总结

<!-- 用通俗大白话讲清：原来有什么问题/需求 → 本次改成了什么 → 实际带来什么效果 -->

## 提交步骤清单

<!-- 列出本 PR 包含的 commit 顺序，方便审查者看清任务拆成了哪几步 -->
- [ ] Step 1: `<commit hash / 简述>`

## 准入检查实测结果

<!-- 贴出实际运行的本地检查或 CI 检查实测输出（不得凭猜测填写） -->
- `python3 -m pytest tests -q`：
- `cd web && npm run build`（如涉及前端）：
- `python3 scripts/validate_delivery_bundle.py --mvllm-root ../mVllm_2`（如涉及交付 bundle）：

## 重点审查与风险提示

- **涉及范围**：
- **需要重点核对的点**：
- **已知边界 / 待后续跟进**：
