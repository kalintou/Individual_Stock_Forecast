# Planner 模块文档

> 本文档记录 `planner/` 目录下每个文件的作用、设计理念和使用方法，供日后回顾。

---

## 模块定位

`planner/` 是 Agent 的**大脑/主季**。

**职责概括：**
- 制定策略：根据问题和音频描述，想出解决方案
- 做出决策：每轮循环中，判断"调工具？回答？还是放弃？"
- 生成定制化 Prompt：让前端听得更准
- 总结证据：在最终答案前，把所有发现压缩成精炼叙述

**和人类的比喻：**
Planner 就像一个侦探。他看到现场（问题）和目击者描述（前端 caption），然后决定：
- 先制定调查计划
- 发现线索不够 → 调取监控（调用工具）
- 收集足够证据 → 给出结论（回答）
- 最后整理成案情简报

---

## 文件逐一说明

### 1. `base.py` — 抽象基类

**作用**：定义所有规划器必须实现的接口。

**核心内容**：
```python
class BasePlanner(ABC):
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def generate_question_oriented_prompt(self, question: str) -> str: ...
    
    @abstractmethod
    def plan(self, question, frontend_output) -> InitialPlan: ...
    
    @abstractmethod
    def decide(self, state, available_tools) -> PlannerDecision: ...
    
    @abstractmethod
    def summarize_evidence(self, state) -> str: ...
```

**四个核心方法的调用时机：**

| 方法 | 调用时机 | 作用 |
|------|---------|------|
| `generate_question_oriented_prompt()` | **Step 1** (`initial_prompt_node`) | 为前端生成定制化 prompt |
| `plan()` | **Step 3** (`initial_plan_node`) | 制定初始调查计划 |
| `decide()` | **Step 4+** (`planner_decision_node`, 每轮循环) | 决定下一步行动 |
| `summarize_evidence()` | **结束前** (`evidence_summarization_node`) | 压缩所有证据 |

**使用示例**：
```python
from planner import BasePlanner

# 错误！不能直接实例化
planner = BasePlanner()  # TypeError: Can't instantiate abstract class
```

---

### 2. `openai_compatible_planner.py` — 真实实现

**作用**：调用 OpenAI 兼容 API 进行推理。

**支持的服务商**：
- OpenAI 官方 (`gpt-4o`)
- xi-ai.cn 等第三方平台
- 阿里云 DashScope (`qwen3.5-plus` 等)

**构造函数**：
```python
planner = OpenAICompatiblePlanner(
    model="gpt-4o",                          # 文本推理模型
    api_key="sk-xxxxx",                      # API Key
    base_url="https://api-2.xi-ai.cn/v1",    # API 地址
    max_retries=3,                           # 失败重试次数
)
```

**API Key 读取优先级：**
1. 传入的 `api_key` 参数
2. 环境变量 `OPENAI_API_KEY`
3. 环境变量 `DASHSCOPE_API_KEY`
4. 都没有 → 报错（Fail-Fast）

---

#### 方法1：`generate_question_oriented_prompt(question)`

**调用时机**：`initial_prompt_node` （流程第 1 步）

**作用**：把用户的原始问题，转换成一个更专业、更具体的音频分析指令。

**示例**：
| 输入 | 输出 |
|------|------|
| "What language is spoken?" | "Analyze the provided audio file to determine the primary language being spoken. Focus on identifying key linguistic features such as phonemes, intonation patterns..." |

**为什么要做这个转换？**
- 用户的问题可能很简单（"这段音频说了什么？"）
- 但前端模型需要更具体的指令才能产生高质量的描述
- Planner 作为"文本专家"，把简单问题"翻译"成专业分析指令

---

#### 方法2：`plan(question, frontend_output)`

**调用时机**：`initial_plan_node` （流程第 3 步）

**作用**：根据问题 + 前端 caption，制定调查计划。

**数据流**：
```
用户问题 + 前端 caption 
    ↓
加载 plan_system.md + plan_user.md
    ↓
填充占位符 {question}, {caption}
    ↓
调用 API
    ↓
解析 JSON 响应 → InitialPlan 对象
```

**返回结构（JSON）**：
```json
{
    "approach": "验证前端 caption 准确性...",
    "focus_points": ["确认语言", "精确转录", "翻译"],
    "possible_tool_types": ["asr", "language detection", "translation"],
    "clarified_intent": "用户想知道音频的确切内容",
    "expected_output_format": "简短回答"
}
```

**关键特性**：
- 要求 API 返回 JSON 格式
- 支持从 markdown 代码块中提取 JSON（兼容性处理）
- 解析失败时报错

---

#### 方法3：`decide(state, available_tools)` ⭐ 最重要

**调用时机**：`planner_decision_node` （流程第 4 步，每轮循环）

**作用**：根据当前所有信息，决定下一步行动。

**核心逻辑**：
```python
# 把整个 AgentState 转换成文本
user_prompt = f"""
Question: {question}
Frontend Caption: {caption}
Initial Plan: {plan}
Evidence Log: 
  1. [frontend] 说话人是男性...
  2. [asr_tool] 转录结果：厨房用具...
Tool Call History:
  1. asr_transcribe (OK)
Available Tools:
  - asr_transcribe: 语音识别
  - language_id: 语言识别
Step: 2 / 5
"""
```

**为什么要把所有信息都塞给 LLM？**

因为 LLM 没有"记忆"，每次 API 调用都是独立的。你必须把**所有历史证据、所有工具调用记录**都告诉它，它才能做出明智的决策。

**比喻**：就像玩狼人杀，每轮发言都要把之前所有人的发言回顾一遍。

**返回结构（JSON）**：
```json
{
    "action": "call_tool",
    "rationale": "需要识别具体语言",
    "selected_tool_name": "language_id",
    "selected_audio_id": "audio_0",
    "draft_answer": null
}
```

**三种行动类型**：

| 行动 | 含义 | 后续流向 |
|------|------|---------|
| `answer` | 证据足够，可以给出最终答案 | `evidence_summarization_node` → `final_answer_node` |
| `call_tool` | 需要更多信息，调用工具 | `tool_executor_node` → `evidence_fusion_node` → 回到 `decision_node` |
| `fail` | 任务不可能或无法恢复 | `failure_node` → END |

---

#### 方法4：`summarize_evidence(state)`

**调用时机**：`evidence_summarization_node` （最终答案前）

**作用**：把所有证据压缩成一段精炼的叙述。

**为什么需要总结？**
- 前端模型（音频模型）可能有输入长度限制
- 原始证据可能很冗长（多条工具输出）
- 总结后的精炼版本更适合传给前端生成最终答案

**示例**：
```
输入（多条证据）：
  1. [frontend] 男性说话人，中文
  2. [asr_tool] 转录：厨房用具
  3. [speaker_id] 说话人 ID：speaker_1

输出（总结后）：
  "A male speaker, speaking in Chinese, mentioned 'kitchen utensils.'"
```

---

### 私有方法

| 方法 | 作用 |
|------|------|
| `_call_api()` | 调用 OpenAI API（纯文本，不需要 `modalities`/`audio` 参数） |
| `_load_prompt()` | 从 `prompts/` 目录读取 `.md` 文件 |
| `_parse_plan_json()` | 解析 plan 的 JSON 响应 |
| `_parse_decision_json()` | 解析 decision 的 JSON 响应 |
| `_format_evidence()` | 将 `list[EvidenceItem]` 序列化为文本 |
| `_format_tool_history()` | 将工具调用历史序列化为文本 |
| `_format_tools()` | 将可用工具列表序列化为文本 |

**关于 `_format_*` 方法**：

LLM 只能理解文本，不能直接读取 Python 对象。这些方法将结构化数据转换为人类可读的文本格式：

```python
# 输入：list[EvidenceItem]
[
    EvidenceItem(source="frontend", content="Male speaker..."),
    EvidenceItem(source="asr_tool", content="Transcription: ..."),
]

# 输出：文本
"1. [frontend] Male speaker...\n2. [asr_tool] Transcription: ..."
```

---

## 数据流程图

### Planner 在整个 Agent 中的位置

```
START
  │
  ▸ initial_prompt_node → planner.generate_question_oriented_prompt()
  │
  ▸ frontend_evidence_node → 前端听音频
  │
  ▸ initial_plan_node → planner.plan()
  │
  ▸ planner_decision_node → planner.decide() ○─────┐
  │                                               │
  ├── ANSWER ───────────────────────────→ ┘
  │                                               │
  ├── CALL_TOOL → tool_executor → evidence_fusion → 回到 decision_node
  │                                               ↑
  └── FAIL ──────────────────────────────→ failure_node → END
  │
  ▸ evidence_summarization_node → planner.summarize_evidence()
  │
  ▸ final_answer_node → 前端生成最终答案
  │
 END
```

### 单个方法的内部流程

```
planner.plan(question, caption)
  │
  ▸ 加载 prompts/plan_system.md
  ▸ 加载 prompts/plan_user.md
  ▸ 填充占位符 {question}, {caption}
  ▸ 调用 _call_api(system, user)
  │    ▸ 构造 messages 列表
  │    ▸ 发送给 OpenAI API
  │    ▸ 获取文本响应
  ▸ 解析 JSON → _parse_plan_json()
  ▸ 返回 InitialPlan 对象
```

---

## 使用示例

### 基本使用

```python
from planner import OpenAICompatiblePlanner
from core.schemas import FrontendOutput

planner = OpenAICompatiblePlanner(
    model="gpt-4o",
    api_key="sk-xxxxx",
    base_url="https://api-2.xi-ai.cn/v1",
)

# 1. 生成定制化 prompt
prompt = planner.generate_question_oriented_prompt("What language is spoken?")

# 2. 制定计划
caption = FrontendOutput(question_guided_caption="A speaker says words.")
plan = planner.plan("What language is spoken?", caption)
print(plan.approach)
print(plan.focus_points)

# 3. 做出决策
from core import create_initial_state
state = create_initial_state("What language?", "D:\\test.wav")
state["initial_frontend_output"] = caption
state["initial_plan"] = plan

tools = [ToolSpec(name="language_id", description="Identify language")]
decision = planner.decide(state, tools)
print(decision.action)  # call_tool / answer / fail
print(decision.selected_tool_name)

# 4. 总结证据
summary = planner.summarize_evidence(state)
```

---

## 与原项目的区别

| 项目 | 原项目 AUDIO_AGENT | 本项目 agent-basic |
|------|------------------|-------------------|
| 规划器适配器 | Qwen2.5、Gemini、OpenAI 等 4+ 个 | 只保留 OpenAICompatiblePlanner |
| 方法数量 | `clarify_intent`、`clarify_question`、`check_format` 等 | 精简为 4 个核心方法 |
| Prompt 文件 | 有 answer_system、verification_system、format_check 等 | 只保留 plan 和 decide 相关 |
| JSON 解析 | 在各适配器中分散实现 | 统一在 OpenAICompatiblePlanner 中 |
| 重试机制 | 有指数退避 | 保留指数退避 |

---

## 常见问题

### Q1: API 返回的不是纯 JSON，解析失败
**现象**：`Failed to parse plan JSON`
**原因**：LLM 可能在 JSON 外包了 markdown 代码块（```json ... ```）。
**解决**：代码已经处理了这种情况，会自动提取代码块内的 JSON。

### Q2: decide() 总是选择同一个工具
**原因**：`decide_rules.md` 里规定了"不要重复调用同一工具"，但规划器可能没有遵守。
**解决**：
1. 在 `decide_rules.md` 里加强规则描述
2. 在代码中添加后置处理：检查是否重复调用
3. 调高 temperature 让模型更"灵活"

### Q3: plan() 返回的 approach 太简短或太空泛
**原因**：System Prompt 对 plan 的要求不够具体。
**解决**：修改 `prompts/plan_system.md`，添加更具体的范例和要求。

### Q4: 运行时提示 "No API key provided"
**原因**：没有传入 api_key，也没有设置环境变量。
**解决**：
```bash
# Windows
set OPENAI_API_KEY=sk-xxxxx

# 或者在代码中传入
planner = OpenAICompatiblePlanner(api_key="sk-xxxxx")
```

---

## 扩展指南

### 如果你想添加一个新的规划器适配器

比如接入 Kimi 的文本模型：

```python
# 新建文件：planner/kimi_planner.py
from planner.base import BasePlanner
from core.schemas import InitialPlan, PlannerDecision

class KimiPlanner(BasePlanner):
    @property
    def name(self) -> str:
        return "kimi_planner"
    
    def plan(self, question, frontend_output) -> InitialPlan:
        # 实现 Kimi 特定的调用逻辑
        ...
    
    def decide(self, state, available_tools) -> PlannerDecision:
        ...
    
    # 其他方法...
```

然后在 `planner/__init__.py` 中导出：
```python
from planner.kimi_planner import KimiPlanner
__all__ = [..., "KimiPlanner"]
```

---

## 测试

运行规划器测试：
```bash
cd agent-basic
D:\anaconda3\envs\agent-basic\python.exe tests\test_planner.py --api-key sk-xxxxx
```

可选参数：
```bash
--api-key sk-xxxxx          # API Key
--base-url https://...      # API 地址
--model gpt-4o              # 模型名称
```
