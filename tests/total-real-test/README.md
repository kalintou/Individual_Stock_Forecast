# Total Real Test - Execution Tracing

This directory demonstrates how to run the agent with full node-level tracing enabled.

## What is Tracing?

When tracing is enabled, every node's input state and output update is recorded with timestamps. After execution, two files are generated:

- `trace.jsonl` - Machine-readable, one JSON object per line
- `trace_report.md` - Human-readable Markdown report

## How to Use

### Option 1: Via main.py (Recommended)

Simply add `--trace` when running the agent:

```bash
cd agent-basic
D:\anaconda3\envs\agent-basic\python.exe main.py \
    --audio "D:\PythonProject\audio-agent\IC0001W0001.wav" \
    --question "请识别这个音频" \
    --api-key sk-xxx \
    --trace \
    --trace-dir ./traces
```

After execution, check `./traces/trace_report.md` for the full execution flow.

### Option 2: Programmatically

```python
from graph import build_agent_graph, write_traces, set_trace_dir

# Enable trace when building the graph
graph = build_agent_graph(
    planner, frontend, fusion, executor, registry,
    enable_trace=True,
)

set_trace_dir("./traces")
final_state = graph.invoke(initial_state)

# Write trace files
jsonl_path, md_path = write_traces()
print(f"Traces written to: {md_path}")
```

## Trace Report Format

Each node gets its own section:

```markdown
## Step 1: `initial_prompt_node` (1200 ms)
### Input State
{question: "...", audio_path: "...", ...}
### Output Update
{question_oriented_prompt: "Analyze this audio for..."}
---

## Step 2: `frontend_evidence_node` (3500 ms)
### Input State
{...}
### Output Update
{initial_frontend_output: {caption: "Kitchen sounds..."}, evidence_log: [...]}
> **Caption**: Kitchen sounds with chopping and speech
---
```

## Notes

- Base64-encoded data (e.g., audio bytes) is automatically replaced with `<base64 data, N chars>`
- Large objects are serialized via Pydantic's `model_dump()`
- If the agent fails mid-execution, traces up to the failure point are still written
