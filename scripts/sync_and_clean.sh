#!/usr/bin/env bash
# 同步主线并安全清理已通过 Merge Commit 合并的 work/* worktree 与本地分支。
#
# 四重安全锁（全部满足才会清理，否则自动跳过）：
#   1. 仅处理 work/* 分支（绝不触碰主线或其他分支）
#   2. 该分支尖端 SHA 必须确已作为某个合并提交的第 2 父提交（^2）进入
#      github/main 的一阶历史（杜绝误删刚从主线切出的新分支！）
#   3. 对应 worktree 必须完全干净（无未提交修改、无未跟踪文件、无非缓存类被忽略本地文件）且未被 lock
#   4. 绝不删除当前命令运行所在的 worktree
#
# 注意：本脚本按 Create a merge commit 合并策略判定“已合并”。
# 若某分支曾被手动 Squash / Rebase 合并，本脚本会保守跳过，需人工确认后 git branch -D。
#
# 用法：
#   bash scripts/sync_and_clean.sh            # 执行同步与安全清理
#   bash scripts/sync_and_clean.sh --dry-run  # 仅预演（不修改远程引用、不改工作区）

set -euo pipefail

REMOTE="github"
MAIN_BRANCH="main"
MAIN_REF="${REMOTE}/${MAIN_BRANCH}"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
elif [ "${1:-}" != "" ]; then
  echo "用法: $0 [--dry-run]" >&2
  exit 2
fi

CURRENT_TOPLEVEL="$(git rev-parse --show-toplevel)"
CURRENT_REALPATH="$(cd "$CURRENT_TOPLEVEL" && pwd -P)"

if $DRY_RUN; then
  echo "==> 1/4 [dry-run] 跳过 git fetch --prune，使用本地已有远程跟踪引用 (${MAIN_REF})..."
else
  echo "==> 1/4 拉取远程最新状态并清理已删远程引用 (${REMOTE})..."
  git fetch --prune "$REMOTE"
fi

if ! git rev-parse --verify --quiet "$MAIN_REF" >/dev/null; then
  echo "❌ 找不到远端主线引用 ${MAIN_REF}，已中止。" >&2
  exit 1
fi

MERGED_TIPS="$(git log --merges --first-parent --format='%P' "$MAIN_REF" | awk '{for (i=2; i<=NF; i++) print $i}')"

is_merged_via_merge_commit() {
  local branch="$1"
  local tip
  tip="$(git rev-parse --verify --quiet "refs/heads/${branch}" || true)"
  [ -n "$tip" ] && grep -Fxq "$tip" <<< "$MERGED_TIPS"
}

MAIN_WT=""
WORK_WT_PATHS=()
WORK_WT_BRANCHES=()
WORK_WT_LOCKED=()

wt_path=""
wt_branch=""
wt_locked="0"
flush_worktree() {
  if [ -n "$wt_path" ] && [ -n "$wt_branch" ]; then
    if [ "$wt_branch" = "$MAIN_BRANCH" ]; then
      MAIN_WT="$wt_path"
    elif [[ "$wt_branch" == work/* ]]; then
      WORK_WT_PATHS+=("$wt_path")
      WORK_WT_BRANCHES+=("$wt_branch")
      WORK_WT_LOCKED+=("$wt_locked")
    fi
  fi
  wt_path=""
  wt_branch=""
  wt_locked="0"
}

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "worktree "*)
      wt_path="${line#worktree }"
      ;;
    "branch refs/heads/"*)
      wt_branch="${line#branch refs/heads/}"
      ;;
    "locked"*)
      wt_locked="1"
      ;;
    "")
      flush_worktree
      ;;
  esac
done < <(git worktree list --porcelain; echo "")

echo "==> 2/4 同步主工作区 (${MAIN_BRANCH})..."
if [ -n "$MAIN_WT" ] && [ -d "$MAIN_WT" ]; then
  if [ -z "$(git -C "$MAIN_WT" status --porcelain)" ]; then
    if $DRY_RUN; then
      echo "  [dry-run] 将同步主工作区: git -C \"$MAIN_WT\" merge --ff-only --no-overwrite-ignore ${MAIN_REF}"
    else
      if ! git -C "$MAIN_WT" merge --ff-only --no-overwrite-ignore "$MAIN_REF"; then
        echo "❌ 同步主工作区失败（可能存在会覆盖本地被忽略文件或非快进分叉的情况），已中止: $MAIN_WT" >&2
        exit 1
      fi
    fi
  else
    echo "  ⚠️ 跳过主工作区同步（存在未提交改动）: $MAIN_WT"
  fi
else
  echo "  ℹ️ 未检测到检出 ${MAIN_BRANCH} 的工作区，跳过主线同步。"
fi

is_rebuildable_cache_path() {
  local rel="$1"
  rel="${rel%/}"
  case "$rel" in
    .pytest_cache|*/.pytest_cache|.pytest_cache/*|*/.pytest_cache/*|\
    __pycache__|*/__pycache__|__pycache__/*|*/__pycache__/*|\
    .mypy_cache|*/.mypy_cache|.mypy_cache/*|*/.mypy_cache/*|\
    .ruff_cache|*/.ruff_cache|.ruff_cache/*|*/.ruff_cache/*|\
    *.pyc|*.pyo|.DS_Store|*/.DS_Store)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

PRESERVED_IGNORED_SAMPLE=""
has_preserved_ignored_files() {
  local wt="$1"
  PRESERVED_IGNORED_SAMPLE=""
  local tmpfile
  tmpfile="$(mktemp)"
  if ! git -C "$wt" status --porcelain=v1 --ignored=matching -z >"$tmpfile" 2>/dev/null; then
    rm -f "$tmpfile"
    PRESERVED_IGNORED_SAMPLE="<git status --ignored 检查失败>"
    return 0
  fi
  local entry path count=0
  while IFS= read -r -d '' entry; do
    if [[ "$entry" == "!! "* ]]; then
      path="${entry#!! }"
      if ! is_rebuildable_cache_path "$path"; then
        if [ "$count" -lt 3 ]; then
          [ -n "$PRESERVED_IGNORED_SAMPLE" ] && PRESERVED_IGNORED_SAMPLE+=", "
          PRESERVED_IGNORED_SAMPLE+="$path"
        fi
        count=$((count + 1))
      fi
    fi
  done < "$tmpfile"
  rm -f "$tmpfile"
  if [ "$count" -gt 3 ]; then
    PRESERVED_IGNORED_SAMPLE+=" 等共 ${count} 项"
  fi
  [ "$count" -gt 0 ]
}

echo "==> 3/4 扫描并安全清理已合并的 work/* worktree..."
removed_wt_count=0
skipped_wt_count=0
PLANNED_REMOVED_BRANCHES=""

for i in "${!WORK_WT_PATHS[@]}"; do
  p="${WORK_WT_PATHS[$i]}"
  b="${WORK_WT_BRANCHES[$i]}"
  locked="${WORK_WT_LOCKED[$i]}"

  if [ ! -d "$p" ]; then
    echo "  ℹ️ 目录已不存在，稍后将由 worktree prune 清理: $p ($b)"
    if $DRY_RUN; then
      PLANNED_REMOVED_BRANCHES+="${b}"$'\n'
    fi
    continue
  fi

  if [ "$locked" = "1" ]; then
    echo "  ⏭️ 跳过已锁定的 worktree (locked): $b ($p)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  p_real="$(cd "$p" && pwd -P)"
  if [ "$p_real" = "$CURRENT_REALPATH" ]; then
    echo "  ⏭️ 跳过当前所在工作区: $p ($b)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if ! is_merged_via_merge_commit "$b"; then
    echo "  ⏭️ 跳过未通过 merge commit 合入主线的分支（含刚切出的新分支）: $b ($p)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if [ -n "$(git -C "$p" status --porcelain)" ]; then
    echo "  ⏭️ 跳过含未提交改动的工作区: $b ($p)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if has_preserved_ignored_files "$p"; then
    echo "  ⏭️ 跳过含被忽略本地文件的工作区（请先备份或手动清理）: $b ($p) -> ${PRESERVED_IGNORED_SAMPLE}"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if $DRY_RUN; then
    echo "  [dry-run] 将删除已合并且干净的 worktree: $p ($b)"
    PLANNED_REMOVED_BRANCHES+="${b}"$'\n'
  else
    if git worktree remove "$p"; then
      echo "  🧹 已删除 worktree: $p ($b)"
    else
      echo "  ⚠️ 删除 worktree 失败，已跳过: $p ($b)"
      skipped_wt_count=$((skipped_wt_count + 1))
      continue
    fi
  fi
  removed_wt_count=$((removed_wt_count + 1))
done

if ! $DRY_RUN; then
  git worktree prune
fi

echo "==> 4/4 扫描并安全清理已合并且未检出的本地 work/* 分支..."
removed_br_count=0
skipped_br_count=0

ACTIVE_BRANCHES=""
while IFS= read -r line; do
  case "$line" in
    "branch refs/heads/"*)
      br="${line#branch refs/heads/}"
      if $DRY_RUN && grep -Fxq "$br" <<< "$PLANNED_REMOVED_BRANCHES"; then
        continue
      fi
      ACTIVE_BRANCHES+="${br}"$'\n'
      ;;
  esac
done < <(git worktree list --porcelain)

while IFS= read -r b; do
  [ -z "$b" ] && continue

  if grep -Fxq "$b" <<< "$ACTIVE_BRANCHES"; then
    echo "  ⏭️ 跳过仍被 worktree 占用的分支: $b"
    skipped_br_count=$((skipped_br_count + 1))
    continue
  fi

  if ! is_merged_via_merge_commit "$b"; then
    echo "  ⏭️ 跳过未通过 merge commit 合入主线的分支: $b"
    skipped_br_count=$((skipped_br_count + 1))
    continue
  fi

  if $DRY_RUN; then
    echo "  [dry-run] 将删除已合并本地分支: $b"
  else
    # 前置已严格校验该分支尖端 SHA 确已作为 merge commit 父提交进入远端主线，
    # 使用 -D 避免在本地 HEAD 落后于远端主线时误报 not fully merged。
    git branch -D "$b"
    echo "  🧹 已删除本地分支: $b"
  fi
  removed_br_count=$((removed_br_count + 1))
done < <(git for-each-ref --format='%(refname:short)' 'refs/heads/work/*')

echo ""
echo "✅ 完成：清理 worktree ${removed_wt_count} 个（跳过 ${skipped_wt_count}），清理本地分支 ${removed_br_count} 个（跳过 ${skipped_br_count}）。"
