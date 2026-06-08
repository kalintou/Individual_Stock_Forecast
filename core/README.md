# Core 模块文档

> 本文档记录 `core/` 目录下每个文件的作用，供日后回顾。

---

## 模块定位

`core/` 是整个 Agent 的**地基**。它不依赖任何其他模块（frontend、planner、tools 等），但所有其他模块都依赖它。

形象比喻：如果 Agent 是一辆汽车，`core/` 就是车轮、轴承、底盘这些**基础零件**。没有它们，发动机、方向盘都装不上。

---

## 文件逐一说明

### 1. `constants.py` — 常量/枚举

**作用**：定义 Agent 在运行过程中可能处于的状态。

**核心内容**：
- `AgentStatus` 枚举：`RUNNING` / `ANSWERED` / `FAILED` / `CLARIFYING`

**什么时候用**：
- Agent 刚启动时，`status = RUNNING`
- 成功给出答案后，`status = ANSWERED`
- 遇到不可恢复的错误时，`status = FAILED`
- Graph 的终止节点会检查这个状态来判断是否结束循环

**和原项目的区别**：
- 原项目有更多状态，精简版只保留最核心的三个

---

### 2. `errors.py` — 异常体系

**作用**：定义 Agent 专属的错误类型，让调试时一眼看出"是哪个组件出了问题"。

**核心内容**（层级结构）：
```
AudioAgentError (总基类)
├── FrontendError      ← 前端（音频模型）出错
├── PlannerError       ← 规划器（文本LLM）出错
├── ToolExecutionError ← 工具执行出错
├── FusionError        ← 证据融合出错
└── StateValidationError ← 状态数据不完整
```

**什么时候用**：
- `FrontendError`：音频文件不存在、API 返回异常、caption为空
- `PlannerError`：LLM API 超时、返回的JSON无法解析
- `ToolExecutionError`：MCP工具进程崩溃、工具参数错误
- `FusionError`：工具返回的结果格式不对，转不成证据
- `StateValidationError`：节点需要的字段在 state 中不存在

**为什么不用 Python 内置的 Exception**：
- 如果都用 `Exception`，报错时你只知道"出错了"，但不知道是哪个组件
- 自定义异常可以带 `details` 字典，保存更多上下文

**和原项目的区别**：
- 完全一致，原项目也是这个层级结构

---

### 3. `schemas.py` — 数据模型（Pydantic）

**作用**：定义 Agent 中所有组件之间传递数据的"合同"。

**形象比喻**：就像工厂里的"零件规格书"——规定了每个零件必须有什么尺寸、什么材料。

**核心数据模型**（按功能分组）：

| 组别 | 模型 | 作用 |
|------|------|------|
| 枚举 | `PlannerActionType` | 规划器的三种行动：ANSWER / CALL_TOOL / FAIL |
| 前端 | `FrontendInput` | 传给前端的输入：问题 + 音频路径 |
| 前端 | `FrontendOutput` | 前端返回的输出：音频描述 caption |
| 证据 | `EvidenceItem` | 一条证据 = 来源 + 内容 + 置信度 |
| 工具 | `ToolSpec` | 工具说明书（名字、功能、参数格式） |
| 工具 | `ToolCallRequest` | 调用工具的请求（调谁、传什么参数） |
| 工具 | `ToolResult` | 工具执行结果（成功/失败、返回数据） |
| 工具 | `ToolCallRecord` | 历史记录（请求 + 结果 + 第几步调的） |
| 规划器 | `ExecutionStep` | 计划中的一步（第几步、干什么、预期输出） |
| 规划器 | `InitialPlan` | 初始计划（策略 + 焦点 + 执行步骤） |
| 规划器 | `PlannerDecision` | 每轮决策（行动 + 理由 + 选的工具） |
| 答案 | `FinalAnswer` | 最终答案 + 置信度 + 推理过程 |

**关键设计：`model_config = {"extra": "forbid"}`**
- 意思："不允许有我没定义的字段"
- 作用：如果 LLM 返回了额外字段，立刻报错
- 这就是 **Fail-Fast** 原则

**关键设计：`@model_validator`**
- 在 `FrontendOutput`、`InitialPlan`、`PlannerDecision` 里都有
- 作用：跨字段验证
  - 例如：`CALL_TOOL` 必须同时提供 `selected_tool_name`
  - 如果只说"要调工具"但没说调哪个，报错

**和原项目的区别**：
- 原项目有 `QuestionClarification`、`FormatCheckResult`、`AudioItem` 等
- 精简版去掉了多音频和格式检查相关的模型，保留了核心框架

---

### 4. `state.py` — LangGraph 状态定义

**作用**：定义 `AgentState`，这是整个 Graph 共享的**中央记忆**。

**形象比喻**：`AgentState` 就像一个**公共笔记本**，所有节点都可以看，也都可以写。

**核心概念：`TypedDict` + `Annotated`**

```python
class AgentState(TypedDict, total=False):
    evidence_log: Annotated[list[EvidenceItem], _append]   # 追加模式
    current_decision: Annotated[PlannerDecision | None, _replace]  # 替换模式
```

- **`_append`**：新数据往后面**追加**（不删除旧的）
  - 用于：`evidence_log`、`tool_call_history`、`planner_trace`
  - 比喻：笔记本里**继续往后写**

- **`_replace`**：新数据**完全覆盖**旧数据
  - 用于：`current_decision`、`latest_tool_result`
  - 比喻：翻到**新的一页**，旧页不要了

**`AgentState` 字段生命周期**：

| 阶段 | 被设置的字段 | 设置者 |
|------|------------|--------|
| 初始化 | `question`, `audio_path`, `max_steps`, `status=RUNNING` | `create_initial_state()` |
| Step 1 | `question_oriented_prompt` | `initial_prompt_node` |
| Step 2 | `initial_frontend_output` | `frontend_evidence_node` |
| Step 3 | `initial_plan` | `initial_plan_node` |
| 循环中 | `current_decision`, `latest_tool_result`, `step_count++` | decision / tool / fusion 节点 |
| 循环中 | `evidence_log` (增长) | `evidence_fusion_node` |
| 结束前 | `evidence_summary` | `evidence_summarization_node` |
| 结束 | `final_answer`, `status=ANSWERED` | `final_answer_node` |
| 失败 | `error_message`, `status=FAILED` | `failure_node` |

**和原项目的区别**：
- 原项目有 `audio_list` (多音额数组)、`format_check_result`、`question_clarification` 等
- 精简版用 `audio_path: str` (单音频)替代了 `audio_list`
- 但保留了 `question_oriented_prompt` 字段（因为你要求保留 `initial_prompt_node`）

---

### 5. `logging.py` — 极简日志

**作用**：在终端打印带标签的运行日志，让你看到 Agent 正在执行哪个节点。

**提供的函数**：
- `log_node_start(node_name, context)` — 节点开始
- `log_node_end(node_name, result)` — 节点结束
- `log_planner_decision(action, rationale, tool_name)` — 记录规划器决策
- `log_error(node_name, error)` — 记录错误
- `log_info(label, data)` — 通用信息

**和原项目的区别**：
- 原项目有完整的 Markdown 日志文件系统（每次运行生成一个 .md 日志文件）
- 精简版先用简单的 `print` 输出

---

### 6. `__init__.py` — 包入口

**作用**：让其他代码可以用 `from core import AgentState` 这种简洁方式导入。

如果没有这个文件，你就得写：
```python
from core.state import AgentState
from core.schemas import FinalAnswer
from core.constants import AgentStatus
```

有了它之后，可以写：
```python
from core import AgentState, FinalAnswer, AgentStatus
```

---

## 如何运行测试

见项目根目录的 `tests/test_core.py` 文件。
