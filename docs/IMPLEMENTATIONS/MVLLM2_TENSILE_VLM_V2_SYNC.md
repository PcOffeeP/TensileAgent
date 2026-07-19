# mVllm_2：`tensile-vlm/v2` 契约与服务端同步实施计划

> 适用仓库：`mVllm_2`
>
> 文档用途：将本文复制到 `mVllm_2` 后，交给该仓库内的 Agent 直接实施。
>
> 当前阶段：可替换视觉模型 MVP。只同步生产推理契约、服务预检和部署身份，不训练、不调参、不评价视觉准确率。

## 一、目标与完成定义

把 `mVllm_2` 从分散的 `tensile-vlm/v1` 契约迁移到唯一、自包含的
`tensile-vlm/v2` artifact，并让同进程视觉服务完整实现 TensileAgent 已固定的协议。

完成后必须满足：

1. `pipeline/contracts/tensile_vlm_v2.json` 与 TensileAgent 中的同名 artifact
   规范化内容及 `contract_hash` 完全一致。
2. 生产服务提供 `GET /v1/tensile/contract`。
3. 每次分析和 Evidence 响应都带实际帧表、request ID 和与预检完全一致的
   `deployment_manifest`。
4. 旧 `tensile-vlm/v1` 不再被生产代码加载，不维护双协议兼容。
5. 模型输出仍只有四个字段；`has_fracture=true` 时次要字段可以分别为 `null`，
   `has_fracture=null` 时其余三项必须全部为 `null`。
6. 不修改训练数据、checkpoint、权重、训练 YAML、数据划分或视觉效果指标。

## 二、施工边界

### 允许修改

- `pipeline/contracts/`
- `pipeline/production_contract.py`
- `pipeline/server_adapter.py`
- `pipeline/server_proxy.py`
- `pipeline/server_deployment_manifest.example.json`
- `pipeline/prompt_library.yaml`，仅限与 v2 artifact 对齐或标记为生成兼容快照
- `tests/test_production_contract.py`
- 与上述生产契约直接相关的少量测试和说明文档

### 禁止修改

- `data/` 中的训练、标注和划分内容
- checkpoint、adapter 或 base model
- 训练超参数和 LLaMA-Factory 训练配置
- 为了让测试通过而放宽 deployment、帧表或模型输出校验
- 视觉识别算法、Prompt 实验或效果门槛
- TensileAgent 主流程

如果仓库事实与本文冲突，先记录证据并停止扩大范围；不要自行恢复 v1 兼容。

## 三、权威 v2 artifact

优先从相邻 TensileAgent 仓库直接复制：

```bash
cp ../TensileAgent/agent/contracts/tensile_vlm_v2.json \
  pipeline/contracts/tensile_vlm_v2.json
```

复制后应得到：

- `contract_version`: `tensile-vlm/v2`
- `contract_hash`:
  `14188762127d5e04896d5fd585e99e8dcfc7cc83ff5c86b9dc11cada93cc9002`
- 8 种断裂类型，新增的第 8 种是 `脆性断裂、齐根断裂`
- 非断裂类型只有 `未断裂`、`未夹紧`
- 不包含 `视频异常`
- `max_frames=8`
- 媒体类型只有 `video/mp4`
- analysis 和 evidence 各自拥有固定 Prompt 与确定性 generation 配置
- Evidence 的可靠性声明为 `experimental`

如果相邻仓库不可用，使用本文末尾的 artifact 附录创建文件。不得手工改写 Prompt、
枚举、generation 或 hash。

删除或停止生产代码引用 `pipeline/contracts/tensile_vlm_v1.json`。历史文件如需保留，
只能移入明确的 archive，不能继续作为运行时 fallback。

## 四、`production_contract.py` 改造

将生产契约加载逻辑收敛为只读取 `pipeline/contracts/tensile_vlm_v2.json`。

必须实现：

```python
CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v2.json"
CONTRACT_VERSION = "tensile-vlm/v2"
```

新增确定序列化函数：

```python
def canonical_contract_bytes(contract: dict[str, Any]) -> bytes:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
```

`load_production_contract()` 必须：

1. 校验所有顶层字段存在。
2. 校验四字段顺序恰好为
   `has_fracture, fracture_between, type, location`。
3. 拒绝非 `tensile-vlm/v2`。
4. 用 `canonical_contract_bytes()` 计算 SHA256。
5. artifact 内 `contract_hash` 不一致时启动失败。
6. 返回 artifact 自身，不再把 YAML Prompt 动态合并进生产契约。

`production_contract_hash()` 必须直接返回已经校验的 artifact
`contract_hash`，不再计算“JSON bytes + NUL + YAML bytes”。

命令行输出字段改为：

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "..."
}
```

### Prompt library 的处理

生产服务只能从 v2 artifact 的 `analysis`、`evidence` 节点读取 Prompt 和 generation。
`pipeline/prompt_library.yaml` 暂时仍可供既有训练样本构造使用，但必须满足：

- 文件顶部注明它是 v2 artifact 的训练兼容快照，不是生产运行时来源。
- 测试强制其 system/user Prompt、四字段 schema 和 8 种枚举与 artifact 一致。
- 本任务不借机重建训练样本，也不修改历史数据。

若仓库内已有安全的生成脚本机制，可以让 YAML 由 artifact 生成；否则本次只建立严格
parity test，不扩大训练流水线重构范围。

## 五、deployment manifest 冻结

预检和每轮响应中的 `deployment_manifest` 必须恰好包含以下 11 个非空字符串字段：

```text
model_version
adapter_version
base_model_version
processor_version
llamafactory_version
transformers_version
config_fingerprint
runtime_device
runtime_dtype
contract_version
contract_hash
```

注意：

- `artifact_version` 重命名为 `adapter_version`。
- `prompt_contract_hash` 重命名为 `contract_hash`。
- `processor_version` 既是 preprocessing 顶层字段，也是 deployment identity 的一部分。
- 不允许用 `unknown`、空字符串或 `REPLACE_*` 启动服务。
- `contract_version` 和 `contract_hash` 必须来自已校验的 v2 artifact，不能由部署 JSON
  任意覆盖。
- 预检快照与每轮 manifest 必须来自同一个启动时冻结对象；请求处理中不得重新从环境变量
  或文件读取并改变身份。

同步更新 `pipeline/server_deployment_manifest.example.json`。示例可以保留
`max_frames=8` 作为服务启动配置，但 GET 和每轮返回的 `deployment_manifest` 只能投影
上述 11 个字段。

## 六、`server_adapter.py` 改造

更新 `wrap_response()`：

1. `processor_info["max_frames"]` 必须严格为 8。
2. `processor_version` 必须为非空且不能是 `unknown`。
3. deployment keys 改成上述 11 项，并要求集合完整。
4. 校验 v2 `contract_version` 和 `contract_hash`。
5. 保留实际帧表校验：
   - 1 到 8 帧；
   - index 从 0 连续递增；
   - timestamp 为有限数；
   - timestamp 严格递增。
6. 每轮生成非空 request ID。
7. 输出结构保持：

```json
{
  "preprocessing": {
    "request_id": "...",
    "processor_version": "...",
    "max_frames": 8,
    "frames": [
      {"index": 0, "timestamp": 0.0}
    ],
    "deployment_manifest": {
      "...": "..."
    }
  }
}
```

不得删掉现有 tensor digest/shape 诊断，但这些字段不属于公共 deployment identity。

## 七、`server_proxy.py` 改造

### 1. 服务启动时冻结身份

`create_integrated_app(chat_model, deployment_info)` 启动时：

- 校验 processor 实际类名与 `processor_version` 一致。
- 校验 `max_frames=8`。
- 调用 production contract loader 完成 hash 自校验。
- 构造一次不可变的 11 字段 deployment manifest。
- 后续 GET 与 POST 都复用同一快照。

### 2. 新增预检端点

新增：

```python
@app.get("/v1/tensile/contract")
async def tensile_contract(raw_request: Request):
    ...
```

鉴权规则必须与 `/v1/chat/completions` 相同。返回结构必须恰好支持：

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "14188762127d5e04896d5fd585e99e8dcfc7cc83ff5c86b9dc11cada93cc9002",
  "deployment_manifest": {
    "model_version": "...",
    "adapter_version": "...",
    "base_model_version": "...",
    "processor_version": "...",
    "llamafactory_version": "...",
    "transformers_version": "...",
    "config_fingerprint": "...",
    "runtime_device": "...",
    "runtime_dtype": "...",
    "contract_version": "tensile-vlm/v2",
    "contract_hash": "..."
  },
  "capabilities": {
    "analysis": true,
    "evidence": true
  }
}
```

不要在预检中暴露本地模型绝对路径、token、API Key 或用户视频信息。

### 3. POST 推理

保留已有 Base64 MP4 校验、临时文件本地化、同进程 processor capture 和非流式限制。

必须新增/确认：

- analysis Prompt 只能来自 artifact 的 `analysis`。
- Evidence Prompt 只能来自 artifact 的 `evidence`。
- 客户端任意文本不得覆盖这两组 Prompt。
- generation 参数从对应 artifact 节点读取。
- 每轮 `wrap_response()` 使用启动时冻结的 deployment snapshot。
- 实际 frame table 和 request ID 每轮都返回。

如果当前 LLaMA-Factory 接口仍需要客户端携带固定 Prompt，可以校验收到的
system/user 文本与 artifact 完全一致；不一致返回 422，不能静默接受。不要把用户自然语言
拼进视觉 Prompt。

### 4. Evidence

Evidence 可以继续复用 `/v1/chat/completions`，由固定 Evidence system Prompt 区分模式。
服务声明 `evidence=true` 的前提是该请求能：

- 使用同一视频处理器；
- 返回同样严格的 preprocessing；
- 使用独立固定 Evidence Prompt；
- 不接收主分析四字段标签作为输入。

## 八、测试施工

重点更新 `tests/test_production_contract.py`，至少覆盖：

1. v2 artifact 必需字段、四字段顺序和 8 种断裂枚举。
2. canonical hash 等于 artifact `contract_hash`。
3. 修改任意 Prompt、schema、generation、video 或 enum 后 hash 校验失败。
4. v1 版本直接拒绝。
5. Prompt library 与 artifact parity。
6. `wrap_response()` 返回完整 11 字段 manifest。
7. 缺少或新增 deployment 字段均拒绝。
8. model、adapter、base model、processor、LLaMA-Factory、transformers、
   config、runtime、contract 任一字段漂移都能被测试识别。
9. 帧表为空、超过 8、索引不连续、timestamp 非有限或不递增均拒绝。
10. GET 预检返回正确 contract、能力和启动快照。
11. GET 与 POST 的 manifest 完全相等。
12. API Key 启用时 GET 和 POST 使用相同鉴权语义。
13. Base64 不进入日志或错误输出。

新增一个跨仓一致性测试；相邻 TensileAgent 存在时必须比较规范化内容和 hash：

```python
sibling = (
    Path(__file__).resolve().parents[2]
    / "TensileAgent"
    / "agent"
    / "contracts"
    / "tensile_vlm_v2.json"
)
```

如果 CI 不包含相邻仓库可以 skip，但本地交付验收时该测试必须实际通过，不能只报告 skip。

建议验证命令：

```bash
python3 -m pytest tests/test_production_contract.py -q
python3 -m pytest tests/test_frame_contract.py -q
python3 -m pipeline.production_contract
git diff --check
```

若完整项目测试命令在 `AGENTS.md` 有额外要求，以该仓库规范为准并一并执行。

## 九、传输 smoke

真实视觉模型可启动时做非阻塞 smoke，不评价识别准确率：

```bash
curl -s http://127.0.0.1:8000/v1/tensile/contract | python3 -m json.tool
```

然后用一个小 MP4 调用 `/v1/chat/completions`，只验收：

- Base64 MP4 可传输；
- 返回结构可解析；
- request ID 非空；
- 帧表为实际 processor capture；
- GET 与 POST deployment manifest 完全相等；
- contract version/hash 正确；
- 不支持的 v1、错误媒体和 drift 均 fail closed。

不得把视觉分类是否正确作为本任务阻塞条件。

## 十、交付清单

Agent 完成施工后必须报告：

- 修改文件列表。
- 最终 contract hash。
- GET 预检示例的脱敏结果。
- 相关测试和全量测试结果。
- 是否实际执行跨仓一致性测试。
- 是否执行真实服务 smoke；若未执行，说明硬件/服务原因。
- 明确声明未修改训练数据、权重与调参配置。

## 附录：权威 `tensile_vlm_v2.json`

以下内容必须与 TensileAgent 快照逐字段一致：

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "14188762127d5e04896d5fd585e99e8dcfc7cc83ff5c86b9dc11cada93cc9002",
  "model_output_fields": ["has_fracture", "fracture_between", "type", "location"],
  "model_output_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": false,
    "required": ["has_fracture", "fracture_between", "type", "location"],
    "properties": {
      "has_fracture": {"type": ["boolean", "null"]},
      "fracture_between": {
        "oneOf": [
          {
            "type": "array",
            "prefixItems": [
              {"type": "integer", "minimum": 0},
              {"type": "integer", "minimum": 1}
            ],
            "items": false,
            "minItems": 2,
            "maxItems": 2
          },
          {"type": "null"}
        ]
      },
      "type": {"type": ["string", "null"]},
      "location": {"type": ["string", "null"]}
    }
  },
  "fracture_types": [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂"
  ],
  "other_types": ["未断裂", "未夹紧"],
  "locations": ["inside_gauge", "outside_gauge"],
  "analysis": {
    "system_prompt": "你是一位材料力学视频分析助手。请根据提供的拉伸试验视频帧序列，基于画面中可见的形貌变化，判断试样是否发生断裂。如果发生断裂，请尽可能指出断裂发生在哪两个相邻采样帧之间、断裂模式以及断裂位置。次要字段无法判断时必须使用 null，不得猜测。请只输出一个合法 JSON 对象，且只包含 has_fracture、fracture_between、type、location 四个字段，不要添加 Markdown 代码块或额外解释。",
    "user_prompt": "请分析这段拉伸试验视频，判断试样是否存在断裂。如果存在断裂，请尽可能指出断裂发生在哪两个相邻采样帧之间，并说明断裂模式和断裂位置；无法判断的次要字段输出 null。",
    "generation": {"do_sample": false, "num_beams": 1, "temperature": 0.0, "max_new_tokens": 256}
  },
  "evidence": {
    "system_prompt": "你是一位材料力学视频观察助手。请只依据当前输入的采样帧，按时间顺序描述试样的可见变化，包括伸长、变细、颈缩、连续性中断、分离、打滑、遮挡或画面异常。不要引用其他分析结果，不要输出分类标签或 JSON，只输出一段简洁的视觉观察。",
    "user_prompt": "请描述这段拉伸试验视频采样帧中实际可见的变化过程。",
    "generation": {"do_sample": false, "num_beams": 1, "temperature": 0.0, "max_new_tokens": 256},
    "reliability": "experimental"
  },
  "video": {
    "max_frames": 8,
    "allowed_media_types": ["video/mp4"],
    "timestamp_semantics": "frames[*].timestamp is a finite, strictly increasing offset in seconds relative to the submitted clip; temp_video_manifest maps each sampled clip timestamp to the original video timeline"
  },
  "validation_rules": {
    "true": "fracture_between, type and location may independently be null; non-null fracture_between must be strictly adjacent [i,i+1]; non-null type and location must be declared enum values",
    "false": "fracture_between and location must be null; type must be 未断裂 or 未夹紧",
    "null": "fracture_between, type and location must all be null"
  }
}
```
