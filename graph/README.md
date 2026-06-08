# Graph Module Documentation

This document records the purpose, design concepts, and usage of each file in the `graph/` directory.

---

## Module Positioning

`graph/` is the **"assembly line"** that wires all modules together into a working agent.

| Role | Description |
|------|-------------|
| **Nodes** | Individual work stations (prompt generation, frontend, planning, tool execution, etc.) |
| **Builder** | The factory floor plan — defines the order of stations and where to branch |
| **State** | The conveyor belt carrying work-in-progress between stations |

**Analogy**: If the agent is a detective agency, `graph/` is the **operations manual** that says: "First the secretary prepares questions, then the field agent visits the scene, then the analyst reviews evidence..."

---

## Why LangGraph?

LangGraph provides three key features we need:

1. **State management**: Every node receives the full state and returns partial updates. LangGraph merges them automatically using our reducers (`_append`, `_replace`).

2. **Conditional edges**: The planner's decision (`ANSWER` / `CALL_TOOL` / `FAIL`) routes execution to different paths.

3. **Cycles**: After executing a tool, the graph loops back to the planner for the next decision — the core of any agent loop.

---

## File-by-File Explanation

### 1. `nodes.py` - Node Functions

**Purpose**: Defines what each station does.

**9 Node Functions**:

| Node | Function | Updates State |
|------|----------|---------------|
| `initial_prompt_node` | Calls `planner.generate_question_oriented_prompt()` | `question_oriented_prompt` |
| `frontend_evidence_node` | Calls `frontend.run()`, converts to evidence | `initial_frontend_output`, `evidence_log` |
| `initial_plan_node` | Calls `planner.plan()` | `initial_plan` |
| `planner_decision_node` | Calls `planner.decide()` | `current_decision`, `planner_trace` |
| `tool_executor_node` | Calls `executor.execute()` | `latest_tool_result`, `tool_call_history` |
| `evidence_fusion_node` | Converts `ToolResult` to `EvidenceItem` | `evidence_log`, `step_count` |
| `evidence_summarization_node` | Calls `planner.summarize_evidence()` | `evidence_summary` |
| `final_answer_node` | Calls `frontend.generate_final_answer()` | `final_answer`, `status=ANSWERED` |
| `failure_node` | Sets error message | `error_message`, `status=FAILED` |

**Key Design: Dependency Injection via `functools.partial`**

Node functions take dependencies as extra arguments:
```python
def initial_prompt_node(state, planner): ...
```

But LangGraph only passes `state`. We bind dependencies in `builder.py`:
```python
from functools import partial
bound_prompt = partial(initial_prompt_node, planner=planner_instance)
graph.add_node("initial_prompt", bound_prompt)
```

This keeps node functions testable (pass mock dependencies directly) while allowing LangGraph to call them with just `state`.

**Async Bridge: `_run_async()`**

`ToolExecutor.execute()` is async (for MCP tools), but LangGraph's sync `invoke()` requires sync nodes. We bridge with:
```python
def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Already in an event loop (Jupyter, etc.)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)
```

---

### 2. `builder.py` - Graph Assembly

**Purpose**: Wires nodes together into a `StateGraph` and compiles it.

**Two Key Functions**:

#### `_route_after_decision(state) -> str`

The **traffic controller** after `planner_decision_node`. Reads the planner's decision and returns the next node name.

```python
def _route_after_decision(state):
    step_count = state.get("step_count", 0)
    max_steps = state.get("max_steps", 10)
    
    # Guard: prevent infinite loops
    if step_count >= max_steps:
        return "failure"
    
    decision = state.get("current_decision")
    if decision.action == "answer":
        return "evidence_summarization"
    elif decision.action == "call_tool":
        return "tool_executor"
    else:
        return "failure"
```

**Critical Defense**: `max_steps` check happens **before** reading the decision. Even if the planner "hallucinates" and keeps saying CALL_TOOL, the graph forces termination after N steps.

#### `build_agent_graph(planner, frontend, fusion, executor, registry) -> CompiledGraph`

**Assembly steps**:

1. **Bind dependencies** with `partial`
2. **Create graph**: `StateGraph(AgentState)`
3. **Add nodes**: `graph.add_node("name", bound_function)`
4. **Set entry point**: `graph.set_entry_point("initial_prompt")`
5. **Add edges**:
   - **Linear edges**: `A -> B -> C` (startup sequence)
   - **Conditional edges**: `planner_decision -> [answer|call_tool|failure]`
   - **Loop edges**: `evidence_fusion -> planner_decision` (cycles back)
   - **End edges**: `final_answer -> END`, `failure -> END`
6. **Compile**: `return graph.compile()`

---

## Visual Graph Structure

```
[START]
   |
   v
+---------------------+
|  initial_prompt     |  Generate question-oriented prompt
+---------------------+
   |
   v
+---------------------+
| frontend_evidence   |  Run frontend on audio, create evidence
+---------------------+
   |
   v
+---------------------+
|   initial_plan      |  Create investigation plan
+---------------------+
   |
   v
+---------------------+
|  planner_decision   |  Decide: ANSWER / CALL_TOOL / FAIL
+---------------------+
   |
   |--(ANSWER)------>+---------------------+
   |                 | evidence_summarization |
   |                 +---------------------+
   |                         |
   |                         v
   |                 +---------------------+
   |                 |   final_answer      |
   |                 +---------------------+
   |                         |
   |                         v
   |                       [END]
   |
   |--(CALL_TOOL)--->+---------------------+
   |                 |   tool_executor     |
   |                 +---------------------+
   |                         |
   |                         v
   |                 +---------------------+
   |                 |  evidence_fusion    |  step_count += 1
   |                 +---------------------+
   |                         |
   +-------------------------+  (loop back to planner_decision)
   |
   |--(FAIL)-------->+---------------------+
                     |     failure         |
                     +---------------------+
                             |
                             v
                           [END]
```

---

## Usage Example

```python
from graph import build_agent_graph
from frontend import OpenAICompatibleFrontend
from planner import OpenAICompatiblePlanner
from fusion import SimpleFusion
from tools import ToolRegistry, ToolExecutor

# Create components
frontend = OpenAICompatibleFrontend(api_key=..., model=...)
planner = OpenAICompatiblePlanner(api_key=..., model=...)
fusion = SimpleFusion()
registry = ToolRegistry()
executor = ToolExecutor(registry)

# Build graph
graph = build_agent_graph(planner, frontend, fusion, executor, registry)

# Create initial state
from core.state import create_initial_state
state = create_initial_state(
    question="What is happening in this audio?",
    audio_path="audio.wav",
    max_steps=5,
)

# Run!
final_state = graph.invoke(state)
print(final_state["final_answer"].answer)
```

---

## Testing Strategy

We test the graph with **100% mocked dependencies**:

| Test | Purpose |
|------|---------|
| `test_graph_compiles` | Graph assembles without errors |
| `test_full_workflow_with_tool_loop` | Planner calls tool once, then answers |
| `test_direct_answer_no_tools` | Planner answers immediately, no tool loop |
| `test_max_steps_forces_failure` | Infinite CALL_TOOL loop is forcibly terminated |

Mock components:
- `MockFrontend`: Returns fixed caption and final answer
- `MockPlanner`: Returns CALL_TOOL on first call, ANSWER on second
- `EchoTool`: Simple internal tool for testing tool execution

---

## Comparison with Original Project

| Item | Original AUDIO_AGENT | This Project agent-basic |
|------|---------------------|-------------------------|
| Graph Framework | Custom async loop | LangGraph StateGraph |
| State Management | Manual dict merging | LangGraph reducers (_append/_replace) |
| Conditional Logic | If/else in loop body | `add_conditional_edges()` |
| Tool Loop | While loop | Cycle in graph (evidence_fusion → planner_decision) |
| Max Steps | Manual counter check | Graph-level `_route_after_decision` guard |
| Node Isolation | Functions modify global state | Pure functions return partial updates |

---

## Common Issues

### Q1: "No synchronous function provided to tool_executor"
**Cause**: LangGraph `invoke()` calls sync nodes, but `tool_executor_node` was async.
**Fix**: Convert to sync node, bridge async executor with `_run_async()`.

### Q2: "CALL_TOOL requires selected_audio_id"
**Cause**: `PlannerDecision` validator required `selected_audio_id` for CALL_TOOL.
**Fix**: Removed requirement — single-audio agent uses `state.audio_path` directly.

### Q3: `log_info()` / `log_error()` argument mismatch
**Cause**: Forgot these functions take `(label, data)` or `(node_name, Exception)`.
**Fix**: Always pass both arguments.

---

## Extension Guide

### Adding a format_check_node

```python
# In nodes.py
def format_check_node(state: AgentState, fusion: BaseFusion) -> dict:
    evidence = state["evidence_log"][-1]
    ok, msg = fusion.format_check(evidence)
    if not ok:
        return {"status": AgentStatus.FAILED, "error_message": msg}
    return {}

# In builder.py
graph.add_node("format_check", bound_format_check)
graph.add_edge("evidence_fusion", "format_check")
graph.add_edge("format_check", "planner_decision")
```

### Adding Human-in-the-Loop

Replace `planner_decision` with an interrupt that pauses for human approval before executing tools:
```python
graph.add_node("human_approval", human_approval_node)
graph.add_edge("planner_decision", "human_approval")
graph.add_conditional_edges("human_approval", route_after_approval)
```

---

## Testing

Run graph tests:
```bash
cd agent-basic
D:\anaconda3\envs\agent-basic\python.exe tests\test_graph.py -v
```
