# Fusion Module Documentation

This document records the purpose, design concepts, and usage of each file in the `fusion/` directory.

---

## Module Positioning

`fusion/` is the agent's **"evidence clerk"**.

| Role | Description |
|------|-------------|
| **Translator** | Converts raw outputs (frontend captions, tool results) into uniform `EvidenceItem` format |
| **Quality Inspector** | Validates evidence content, confidence, and source |
| **Archivist** | Organizes all findings so the planner can read them uniformly |

**Analogy**: The frontend is a witness who gives a verbal statement. Tools are forensic labs that produce technical reports. Fusion is the **clerk** who types both into the same standardized form so the detective (planner) can review them side by side.

---

## Why Do We Need Fusion?

Without Fusion, the planner would need to understand multiple formats:

```python
# Without Fusion -- planner sees heterogeneous data
planner sees: FrontendOutput(question_guided_caption="dog barking")
planner sees: ToolResult(output={"text": "hello", "language": "en"})
planner sees: ToolResult(success=False, error_message="Audio too short")
# Planner must handle each format differently -- complexity explosion
```

With Fusion, everything becomes `EvidenceItem`:

```python
# With Fusion -- planner sees uniform data
planner sees: EvidenceItem(source="frontend", content="dog barking", confidence=0.8)
planner sees: EvidenceItem(source="asr", content='{"text": "hello"}', confidence=0.9)
planner sees: EvidenceItem(source="vad", content="Audio too short", confidence=0.0)
# Planner reads .source, .content, .confidence uniformly
```

---

## File-by-File Explanation

### 1. `base.py` - Abstract Base Class

**Purpose**: Defines the interface all fusion implementations must satisfy.

**Core Content**:
```python
class BaseFusion(ABC):
    @abstractmethod
    def frontend_to_evidence(self, frontend_output: FrontendOutput) -> EvidenceItem: ...
    @abstractmethod
    def tool_result_to_evidence(self, tool_result: ToolResult) -> EvidenceItem: ...
    @abstractmethod
    def format_check(self, evidence: EvidenceItem) -> tuple[bool, str]: ...
```

**Three Core Methods**:

| Method | Must Implement? | Purpose |
|--------|-----------------|---------|
| `frontend_to_evidence()` | Yes | Convert `FrontendOutput` → `EvidenceItem` |
| `tool_result_to_evidence()` | Yes | Convert `ToolResult` → `EvidenceItem` |
| `format_check()` | Yes | Validate evidence quality |

**`validate_evidence()` (convenience wrapper)**:

Not abstract. Calls `format_check()` and raises `FusionError` if invalid. Subclasses don't need to override it.

**Why Abstract Base Class?**

Future fusion strategies may differ:
- `SimpleFusion`: Direct translation (current)
- `SmartFusion`: Deduplication, merging related evidence
- `LLMFusion`: Rewrite multiple evidence into coherent narrative

With `BaseFusion`, graph nodes call `fusion.frontend_to_evidence()` without caring which strategy is active.

---

### 2. `simple_fusion.py` - Simple Fusion Implementation

**Purpose**: Straightforward conversion with JSON serialization and basic validation.

**Design Philosophy**: "Do the minimum necessary." No LLM rewriting, no deduplication. Just clean, consistent translation.

**`frontend_to_evidence()`**:

```python
EvidenceItem(
    source="frontend",
    content=caption.strip(),
    evidence_type="caption",
    confidence=0.8,
    metadata={"timestamp": ...},
)
```

| Field | Value | Reason |
|-------|-------|--------|
| `source` | `"frontend"` | Fixed identifier |
| `confidence` | `0.8` | Frontend captions are generally reliable but can hallucinate |
| `evidence_type` | `"caption"` | Natural language description, not structured data |

**`tool_result_to_evidence()`**:

Two branches based on `tool_result.success`:

| Result | `content` | `evidence_type` | `confidence` |
|--------|-----------|-----------------|--------------|
| Success | `json.dumps(output)` | `"structured"` | `0.9` |
| Failure | `error_message` | `"error"` | `0.0` |

**Why `json.dumps()` for success?**

Tool `output` is a `dict[str, Any]`. The planner reads `EvidenceItem.content` as a string. JSON serialization preserves all structured data in a text format the planner can parse.

**Key parameters**:
- `ensure_ascii=False`: Chinese characters display normally
- `default=str`: Fallback for non-JSON-serializable objects (e.g., datetime)

**`format_check()`**:

Three validation rules:

| Rule | Check | Fail Message |
|------|-------|--------------|
| 1 | `source` non-empty | `"Missing or empty source"` |
| 2 | `content` non-empty | `"Missing or empty content"` |
| 3 | `confidence` in [0.0, 1.0] | `"Confidence X out of range [0.0, 1.0]"` |

---

## Data Flow Diagram

### Frontend Evidence Path

```
frontend_evidence_node
    ├── frontend.run(question, audio_path)
    │       └── FrontendOutput(caption="dog barking...")
    │
    ├── fusion.frontend_to_evidence(frontend_output)
    │       └── EvidenceItem(
    │               source="frontend",
    │               content="dog barking...",
    │               confidence=0.8,
    │           )
    │
    └── return {"evidence_log": [evidence]}
            # LangGraph _append reducer adds to list
```

### Tool Evidence Path

```
tool_executor_node
    ├── executor.execute(request)
    │       └── ToolResult(tool_name="asr", output={...}, success=True)
    │
    └── return {"latest_tool_result": tool_result}
            # _replace reducer overwrites this field

evidence_fusion_node
    ├── fusion.tool_result_to_evidence(state["latest_tool_result"])
    │       └── EvidenceItem(
    │               source="asr",
    │               content='{"text": "hello"}',
    │               confidence=0.9,
    │           )
    │
    └── return {
            "evidence_log": [evidence],
            "step_count": state["step_count"] + 1,
        }
```

### Format Check Path

```
format_check_node (future addition)
    ├── latest_evidence = state["evidence_log"][-1]
    ├── ok, msg = fusion.format_check(latest_evidence)
    │
    └── if not ok:
            return {"status": AgentStatus.FAILED, "error_message": msg}
        else:
            return {}  # Continue normally
```

---

## Usage Examples

### Convert Frontend Output to Evidence
```python
from fusion import SimpleFusion
from core.schemas import FrontendOutput

fusion = SimpleFusion()
fe_out = FrontendOutput(question_guided_caption="Kitchen sounds detected")
evidence = fusion.frontend_to_evidence(fe_out)

print(evidence.source)     # "frontend"
print(evidence.content)    # "Kitchen sounds detected"
print(evidence.confidence) # 0.8
```

### Convert Tool Result to Evidence
```python
from core.schemas import ToolResult

tr = ToolResult(
    tool_name="asr_transcribe",
    success=True,
    output={"text": "Turn off the lights", "language": "en"},
)
evidence = fusion.tool_result_to_evidence(tr)

print(evidence.source)     # "asr_transcribe"
print(evidence.content)    # '{"text": "Turn off the lights", "language": "en"}'
print(evidence.confidence) # 0.9
```

### Validate Evidence
```python
from core.schemas import EvidenceItem

# Tuple-based check (non-throwing)
ev = EvidenceItem(source="", content="test", confidence=0.5)
ok, msg = fusion.format_check(ev)
print(ok)   # False
print(msg)  # "Missing or empty source"

# Exception-based check (throwing)
ev = EvidenceItem(source="", content="test", confidence=0.5)
try:
    fusion.validate_evidence(ev)
except FusionError as e:
    print(e.message)  # "Evidence validation failed: Missing or empty source"
```

---

## Comparison with Original Project

| Item | Original AUDIO_AGENT | This Project agent-basic |
|------|---------------------|-------------------------|
| Evidence Conversion | Embedded in graph nodes | Extracted into dedicated Fusion module |
| Validation | Minimal | Explicit `format_check()` with rules |
| Deduplication | Not implemented | Not implemented (future: `SmartFusion`) |
| Error Handling | Generic exceptions | Specific `FusionError` with details |

---

## Extension Guide

### Adding a SmartFusion (with Deduplication)

```python
class SmartFusion(BaseFusion):
    def tool_result_to_evidence(self, tool_result: ToolResult) -> EvidenceItem:
        # First do simple conversion
        evidence = SimpleFusion().tool_result_to_evidence(tool_result)
        # Then check for duplicates in existing log
        # ...deduplication logic...
        return evidence
```

---

## Testing

Run fusion tests:
```bash
cd agent-basic
D:\anaconda3\envs\agent-basic\python.exe tests\test_fusion.py -v
```

All 13 tests pass:
- 2 frontend conversion tests (success + empty caption)
- 3 tool conversion tests (success + failure + empty name)
- 5 format check tests (valid + empty source + empty content + None content + confidence bounds)
- 2 validate_evidence tests (pass + raise)
- 1 name property test (implicit)
