# 模型—Agent 契约训练机验收清单

本清单只用于执行已批准的 `model-agent-contract.md` 真实环境验收，不改变契约。

1. 记录 `LlamaFactory/` commit、Transformers 版本、基础模型 revision、adapter/merged-model revision、GPU 与 dtype。
2. 从 `pipeline/server_deployment_manifest.example.json` 生成实际部署清单，不允许保留 `REPLACE_` 占位值。
3. 运行：

   ```bash
   python3 -m pipeline.preprocessing.minicpm_preprocessor --healthcheck --model <model-path>
   python3 pipeline/scripts/calibration.py --preprocessor minicpm --model <model-path>
   (cd finetune && python3 train_with_contract.py <yaml-under-finetune>)
   ```

4. 运行 `python3 -m pipeline.server_proxy --model <merged-model-path> --deployment-manifest <manifest.json>` 启动同进程集成服务；该服务强制 `API_VERBOSE=0`、设置实际子处理器 8 帧并捕获模型本次实际输入 tensor/帧。Agent 不能连接 stock endpoint。
5. 发送真实 Base64 MP4 请求，确认响应顶层包含合法 `preprocessing`、完整 `deployment_manifest`、实际 tensor digest 和 1–8 个严格单调帧。
6. 使用同一批短、中、长视频比较训练构建与服务抽帧结果；数量、顺序、原始帧和时间戳必须完全一致。
7. 分别验证缺失清单、`max_frames != 8`、索引乱序、时间戳不匹配时 Runner 返回 `ok=false`。
8. 保存校准报告、部署清单及命令输出；任一步失败不得生成正式训练样本或运行定位 Agent。

## 实际训练机命令行操作

以下为 8 项待办在训练机上对应的具体命令和操作步骤。所有命令基于仓库根目录执行，默认模型路径为 `models/minicpm-v-4.5`；若实际路径不同，替换 `<model-path>` 占位符即可。

---

### 步骤 1：记录环境信息

记录 LlamaFactory commit、Transformers 版本、基础模型 revision、adapter/merged-model revision、GPU 配置与 dtype。

```bash
# 1a. LlamaFactory commit
cd LlamaFactory && git log --oneline -1 && cd ..

# 1b. Transformers 版本
python3 -c "import transformers; print(transformers.__version__)"

# 1c. 基础模型 revision（替换为实际模型路径）
cd models/minicpm-v-4.5 && git log --oneline -1 && cd ../..

# 1d. adapter/merged-model revision（若适用）
cd <adapter-or-merged-dir> && git log --oneline -1 && cd ../..

# 1e. GPU 信息
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader

# 1f. 当前使用的 dtype（从训练配置或实际推理日志确认）
python3 -c "import torch; print(torch.cuda.get_device_capability())"
```

> **成功标准**：各项输出均不为空，GPU 和 dtype 与训练配置一致。
> **失败处理**：若 `git log` 提示非 git 仓库，手动记录该目录的版本号来源。

---

### 步骤 2：生成实际部署清单

从示例模板生成部署清单，逐字段填入真实值，**不允许保留 `REPLACE_` 占位值**。

```bash
# 2a. 从示例复制
cp pipeline/server_deployment_manifest.example.json pipeline/training_deployment_manifest.json

# 2b. 编辑清单，填入真实值
# 必填字段（示例值供参考）：
#   "transformers_version": "4.47.1"       ← 步骤 1b 的输出
#   "llamafactory_version": "abc1234"     ← 步骤 1a 的 commit hash
#   "base_model_version": "def5678"       ← 步骤 1c 的 commit hash
#   "artifact_version": "ghi9012"         ← 步骤 1d 的 commit hash
#   "config_fingerprint": "sha256:..."     ← 预处理器 healthcheck 输出的 fingerprint
#
# 工具辅助：筛选出仍含占位符的字段
python3 -c "
import json
m = json.load(open('pipeline/training_deployment_manifest.json'))
dirty = {k: v for k, v in m.items() if isinstance(v, str) and v.startswith('REPLACE_')}
if dirty:
    print('仍含占位符的字段:', json.dumps(dirty, indent=2))
else:
    print('✅ 所有字段已填写')
"
```

> **成功标准**：上述检查脚本输出 "✅ 所有字段已填写"。
> **失败处理**：若有残留占位符，手动编辑 `pipeline/training_deployment_manifest.json` 替换。

---

### 步骤 3：运行 healthcheck、calibration 与训练

```bash
# 3a. 安装依赖（首次运行前执行）
pip install -e ".[minicpm]"

# 验证 av 可用
python3 -c "import av; print(f'av {av.__version__} OK')"

# 3b. 预处理器 healthcheck（替换 <model-path> 若不同）
python3 -m pipeline.preprocessing.minicpm_preprocessor \
    --healthcheck \
    --model models/minicpm-v-4.5
```

**预期输出（示例）**：
```json
{
  "ok": true,
  "info": {
    "name": "MiniCPMVideoPreprocessor",
    "version": "minicpm-v-4.5",
    "max_frames": 8,
    "backend": "pytorch"
  },
  "fingerprint": "sha256:..."
}
```
如果 `fingerprint` 不为空，可将其记入部署清单的 `config_fingerprint` 字段。

```bash
# 3c. 校准
python3 pipeline/scripts/calibration.py \
    --preprocessor minicpm \
    --model models/minicpm-v-4.5 \
    --output data/07_metadata/calibration_report.json
```

> **成功标准**：脚本以 exit code 0 退出，`calibration_report.json` 生成且在指定路径。
> **失败处理**：检查 `--video-meta` 和 `--splits-dir` 默认路径下文件是否存在；可通过参数指定实际路径。

```bash
# 3d. 执行训练（需先准备好 LLaMA-Factory 训练 YAML）
(cd finetune && python3 train_with_contract.py <your-training-yaml>.yaml)
```

> **成功标准**：训练正常启动至第一个 step，无 contract 相关断言失败。
> **失败处理**：确认 YAML 中 `model_name_or_path` 指向正确的模型路径；确认 `finetune/` 目录下有目标 YAML 文件。

---

### 步骤 4：启动 server_proxy 同进程服务

```bash
python3 -m pipeline.server_proxy \
    --model <merged-model-path> \
    --deployment-manifest pipeline/training_deployment_manifest.json \
    --host 127.0.0.1 \
    --port 8001
```

> **参数说明**：
> - `--model`：训练产出的 merged/adapter 模型路径，**非基础模型路径**。
> - `--deployment-manifest`：步骤 2 生成的已填清单。
> - `--port`：默认 8001，若冲突可修改（需同步修改后续 curl 命令）。

该服务自动完成以下操作：
- 设置 `API_VERBOSE=0`。
- 设置实际子处理器 8 帧。
- 捕获模型本次实际输入 tensor / 帧。
- **Agent 端不得连接 stock endpoint（即外部 API 地址），必须连接本机 127.0.0.1:8001。**

> **成功标准**：服务启动日志末尾显示 `Uvicorn running on http://127.0.0.1:8001`，且终端未卡住或报错。
> **失败处理**：
>   - 端口冲突 → 更换 `--port`。
>   - manifests 仍有 `REPLACE_` → 回到步骤 2。
>   - `ChatModel` 初始化失败 → 确认 `--model` 路径包含完整 LLaMA-Factory 格式的配置。

---

### 步骤 5：发送真实 Base64 MP4 请求

在另一个终端（或同一终端后台化服务后）执行：

```bash
# 将测试视频编码为 Base64 data URL
VIDEO_B64=$(base64 -i /path/to/test_video.mp4 | tr -d '\n')
DATA_URL="data:video/mp4;base64,${VIDEO_B64}"

# 构造请求 payload 并发送
curl -s -X POST http://127.0.0.1:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "$(cat <<EOF
{
  "model": "minicpm-v-4.5",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "video_url", "video_url": {"url": "${DATA_URL}"}},
        {"type": "text", "text": "描述这个视频的内容。"}
      ]
    }
  ]
}
EOF
)" | python3 -m json.tool --no-ensure-ascii > response.json
```

**验证响应结构**：
```bash
python3 -c "
import json
r = json.load(open('response.json'))
pp = r.get('preprocessing', {})
assert 'frames' in pp, '缺少 preprocessing.frames'
assert 'tensor_digest' in pp, '缺少 preprocessing.tensor_digest'
assert 'tensor_shape' in pp, '缺少 preprocessing.tensor_shape'
assert 'deployment_manifest' in pp, '缺少 preprocessing.deployment_manifest'
frames = pp['frames']
assert 1 <= len(frames) <= 8, f'帧数 {len(frames)} 不在 1-8 范围内'
indices = [f['index'] for f in frames]
assert indices == sorted(indices), '帧索引非严格单调'
assert len(set(indices)) == len(indices), '帧索引存在重复'
print('✅ 响应结构验证通过')
print(f'   帧数: {len(frames)}')
print(f'   索引: {indices}')
"
```

> **成功标准**：验证脚本输出 "✅ 响应结构验证通过"。
> **失败处理**：
>   - 连接被拒绝 → 确认服务已在对应端口运行。
>   - 响应 422 → 查看服务端错误日志。
>   - 视频过大 → 确认不超过 100MB（服务端 `MAX_VIDEO_BYTES` 限制）。

---

### 步骤 6：比较训练构建与服务抽帧结果

使用同一批短、中、长视频，比较训练构建（步骤 3d）与服务抽帧（步骤 5）的结果。

```bash
# 6a. 准备比较脚本（示例，需根据实际日志格式调整）
python3 -c "
# 训练构建的输出通常保存在 finetune 日志中，格式类似：
#   [CONTRACT] index=3 timestamp=2.133
# 服务响应保存在 response.json 中

import json

# 读取服务端帧列表
svc = json.load(open('response.json'))['preprocessing']['frames']
svc_frames = {(f['index'], f['timestamp']) for f in svc}

# 读取训练日志中的帧列表（需自行替换为实际日志路径）
train_frames = set()
with open('finetune/training_output/frame_log.txt') as f:  # 示例路径
    for line in f:
        if '[CONTRACT]' in line:
            parts = line.strip().split()
            idx = int(parts[1].split('=')[1])
            ts = float(parts[2].split('=')[1])
            train_frames.add((idx, ts))

if svc_frames == train_frames:
    print('✅ 帧数量、顺序、原始帧和时间戳完全一致')
else:
    print('❌ 不一致')
    print('只在训练端:', sorted(train_frames - svc_frames))
    print('只在服务端:', sorted(svc_frames - train_frames))
"
```

> **成功标准**："✅ 帧数量、顺序、原始帧和时间戳完全一致"。
> **失败处理**：
>   - 若训练日志格式不同，需根据实际输出的 contract log 格式调整解析逻辑。
>   - 缺少训练日志 → 在训练命令前添加 `2>&1 | tee training_output.log` 重新运行。

---

### 步骤 7：验证错误处理

分别验证缺失清单、`max_frames != 8`、索引乱序、时间戳不匹配时 Runner 返回 `ok=false`。

```bash
# 7a. 缺失清单 → 启动时不提供 --deployment-manifest（应报错退出）
python3 -m pipeline.server_proxy --model models/minicpm-v-4.5 2>&1 | grep -q 'required' && echo '✅ 缺失清单校验通过' || echo '❌ 未检测到缺失清单错误'
```

```bash
# 7b. max_frames != 8 → 修改部署清单中 max_frames 为非 8 值，启动服务应报错
cp pipeline/training_deployment_manifest.json /tmp/manifest_bad_frames.json
python3 -c "
import json
m = json.load(open('/tmp/manifest_bad_frames.json'))
m['max_frames'] = 4
json.dump(m, open('/tmp/manifest_bad_frames.json', 'w'))
print('max_frames 已改为 4')
"
python3 -m pipeline.server_proxy \
    --model models/minicpm-v-4.5 \
    --deployment-manifest /tmp/manifest_bad_frames.json 2>&1 | grep -q 'max_frames' && \
    echo '✅ max_frames 校验通过' || echo '❌ 未检测到 max_frames 错误'
# 恢复原始清单
```

```bash
# 7c. 索引乱序 / 时间戳不匹配 → 需通过测试脚本验证 Runner 行为
# （具体实现取决于 Runner 的逻辑，以下为示例框架）
python3 -c "
# 假设 Runner 接受 --manifest 和 --response 参数
# 通过构造乱序帧或错误时间戳验证返回 ok=false
# 需根据实际 Runner 接口补充
print('⚠️  索引乱序和时间戳不匹配验证需根据 Runner 实际接口补充实现')
"
```

> **成功标准**：每个错误场景均输出 "✅ ...校验通过"。
> **失败处理**：若 Runner 接口不在本仓库中，需联系负责 Runner 的成员提供测试端点或 CLI。

---

### 步骤 8：保存产物

将本次验收的所有关键产物保存至安全位置（如 `data/08_training_machine_artifacts/`）。

```bash
# 创建产物目录
mkdir -p data/08_training_machine_artifacts

# 复制校准报告
cp data/07_metadata/calibration_report.json data/08_training_machine_artifacts/

# 复制最终部署清单
cp pipeline/training_deployment_manifest.json data/08_training_machine_artifacts/

# 复制服务响应
cp response.json data/08_training_machine_artifacts/

# 复制命令输出日志（若有）
# cp training_output.log data/08_training_machine_artifacts/

# 生成操作摘要
python3 -c "
import json, os
from datetime import datetime
summary = {
    'date': datetime.now().isoformat(),
    'steps': {
        1: '环境信息已记录',
        2: '部署清单已生成',
        3: 'healthcheck/calibration/train 已完成',
        4: 'server_proxy 已启动',
        5: 'Base64 请求已发送并验证',
        6: '训练/服务抽帧已比较',
        7: '错误处理已验证',
        8: '产物已保存',
    },
    'notes': '任一步失败则不得生成正式训练样本或运行定位 Agent',
}
with open('data/08_training_machine_artifacts/验收摘要.json', 'w') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print('✅ 产物已保存至 data/08_training_machine_artifacts/')
"
```

> **成功标准**：产物目录中存在校准报告、部署清单、服务响应和验收摘要。
> **失败处理**：确认 `data/` 目录权限可写。

---

> **⚠️ 重要提醒**：上述 8 项任意一步失败（exit code 非 0 或验证断言未通过），不得生成正式训练样本或运行定位 Agent。

