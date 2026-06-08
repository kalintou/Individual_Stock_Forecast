# Tools Module Documentation

This document records the purpose, design concepts, and usage of each file in the `tools/` directory.

---

## Module Positioning

`tools/` is the agent's **"hands" and "toolbox"**.

| Role | Description |
|------|-------------|
| **Hands** | Execute specific tasks (speech recognition, speaker separation, file processing, etc.) |
| **Toolbox** | Manage all tools: know what exists, how to use them, and how to handle results |

**Analogy**: Tools are like a detective's **logistics support**. The detective says "I need surveillance footage", and logistics fetches it. The detective doesn't need to know how the surveillance works, only the results.

---

## Two Types of Tools

This framework supports two types of tools:

### 1. Internal Tools

Implemented directly as Python classes, running in the same process.

```python
class MyTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="my_tool", description="...")
    
    def invoke(self, request: ToolCallRequest) -> ToolResult:
        # Write Python code directly
        return ToolResult(tool_name="my_tool", success=True, output={...})
```

**Use case**: Simple, lightweight tools without complex dependencies.

### 2. MCP Tools (Model Context Protocol)

Run in independent processes, communicating via JSON-RPC.

```
Agent Process                    MCP Tool Process (independent)
   |                                    |
   |  {"method": "tools/call"}         |
   | -------------------------------->  |
   |                                    |
   |  <-- {"result": {...}}            |
```

**Use case**: Heavy tools with complex dependencies (e.g., PyTorch models) that need isolation to avoid conflicts.

---

## File-by-File Explanation

### 1. `base.py` - Abstract Base Class

**Purpose**: Defines the interface all tools must implement.

**Core Content**:
```python
class BaseTool(ABC):
    @abstractmethod
    def spec(self) -> ToolSpec: ...       # Tool specification
    @abstractmethod
    def invoke(self, request) -> ToolResult: ...  # Execution logic
```

**Two Core Methods**:

| Method | Must Implement? | Purpose |
|--------|-----------------|---------|
| `spec` | Yes | Returns the tool's "ID card" (name, description, parameter format) |
| `invoke()` | Yes | Actually executes the tool |

**Why Abstract Base Class?**

Whether internal Python tools or MCP external tools, the agent sees them uniformly as `BaseTool`:
```python
# The agent doesn't care if it's internal or MCP
result = tool.invoke(request)
```

---

### 2. `registry.py` - Tool Registry

**Purpose**: Manages all registered tools, like a "contact list".

**Core Methods**:

| Method | Purpose | Usage Scenario |
|--------|---------|----------------|
| `register(tool)` | Add a tool to the registry | When the agent starts, register all available tools |
| `get(name)` | Find a tool by name | When `tool_executor_node` needs to execute a tool |
| `list_specs()` | List all tool specifications | When `planner_decision_node` lets the planner know what tools are available |
| `has_tool(name)` | Check if a tool exists | Validation |

**Data Flow**:
```
Agent Startup:
  MyASRTool() -> register() -> stored in _tools["asr_transcribe"]
  MyVADTool() -> register() -> stored in _tools["vad_detect"]

Planner Decision:
  list_specs() -> [ToolSpec("asr_transcribe"), ToolSpec("vad_detect")]
  -> Planner sees these two tools and decides which to call

Tool Execution:
  get("asr_transcribe") -> returns MyASRTool instance
  -> calls instance.invoke(request)
```

**Why use dict `_tools: dict[str, BaseTool]`?**

Because **name-based lookup** is the fastest (O(1)). When the planner says "call `asr_transcribe`", it instantly finds the corresponding tool instance.

---

### 3. `executor.py` - Tool Executor

**Purpose**: Actually calls the tool's `invoke()` method. The "bridge" between Registry and Graph nodes.

**Why need Executor?**

Without Executor, `tool_executor_node` would need to directly manipulate the Registry:
```python
# Pseudocode without Executor
tool = registry.get("asr_transcribe")  # Find
tool.validate_request(request)          # Validate
result = tool.invoke(request)           # Execute
# Also need to handle timing, error wrapping, logging...
```

**Executor encapsulates these steps**, `tool_executor_node` only needs one line:
```python
result = await executor.execute(request)
```

**`execute()` 4 Steps**:

| Step | Code | Purpose |
|------|------|---------|
| 1 | `registry.get(tool_name)` | Find tool instance by name |
| 2 | `tool.validate_request(request)` | Check if request is valid |
| 3 | `tool.invoke(request)` | **Actually execute the tool** |
| 4 | Record `execution_time_ms` | Calculate execution time |

**Why `async`?**
```python
async def execute(self, request) -> ToolResult:
```

Because **MCP tools are external processes**, communicating via JSON-RPC is **asynchronous**. Even if internal tools are synchronous, using a unified async interface means Graph nodes don't need to care about the underlying difference.

---

### 4. `mcp/schemas.py` - MCP Data Models

**Purpose**: Defines JSON-RPC message formats for MCP protocol.

**Four Data Models**:

| Model | Purpose |
|-------|---------|
| `MCPServerConfig` | How to launch an MCP server (command, working directory, env vars) |
| `MCPTool` | Tool definition reported by an MCP server |
| `JSONRPCRequest` | Request format sent to MCP server |
| `JSONRPCResponse` | Response format returned by MCP server |

**What is JSON-RPC?**

A **remote call protocol** based on JSON:
- Request: `{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}`
- Response: `{"jsonrpc": "2.0", "id": 1, "result": {...}}`

Like calling a restaurant to order: you say "I want fried rice" (method + params), they say "OK, 15 minutes" (result).

---

### 5. `mcp/client.py` - MCP Client

**Purpose**: Actually communicates with external tool processes.

**Core Mechanism**: Subprocess + stdin/stdout

```
Agent Process (Python)          MCP Server Process (independent Python env)
   |                                   |
   |  Launch: subprocess.Popen()      |
   | --------------------------------> |
   |                                   |
   |  Write stdin: {"method":"tools/call"...}
   | --------------------------------> |
   |                                   |
   |  Read stdout: {"result":...}     |
   | <-------------------------------- |
   |                                   |
   |  Terminate: process.terminate()  |
   | --------------------------------> |
```

**Key Point**: Two processes exchange JSON messages via **stdin (standard input) / stdout (standard output)**.

**5 Core Methods**:

| Method | Purpose |
|--------|---------|
| `start()` | Launch tool process with `subprocess.Popen()` |
| `stop()` | Graceful shutdown -> forced termination -> kill process |
| `list_tools()` | Ask tool process: "What tools do you have?" |
| `call_tool()` | Ask tool process: "Execute this tool with these parameters" |
| `_send_request()` | **Core method**: Write JSON-RPC request to stdin, read response from stdout |

**`_send_request()` Core Code**:
```python
# 1. Construct JSON-RPC request
request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}

# 2. Serialize to JSON string, add newline
request_line = json.dumps(request) + "\n"

# 3. Write to subprocess stdin
process.stdin.write(request_line)
process.stdin.flush()

# 4. Read one line from subprocess stdout
response_line = process.stdout.readline()

# 5. Parse JSON response
response = json.loads(response_line)
```

**Why add `\n`?** Because `readline()` reads line by line, `\n` means "end of one message".

**Why `asyncio.Lock()`?**
```python
async with self._lock:
    # Send request + read response
```

Prevents **multiple requests from being sent simultaneously** causing response confusion. Like queuing to buy tickets - one person finishes before the next.

---

### 6. `mcp/server_manager.py` - MCP Server Manager

**Purpose**: Manages **multiple** MCP server lifecycles.

**Why need it?**

Suppose you have 3 MCP tools:
- ASR speech recognition
- Speaker separation
- VAD voice activity detection

Each tool is an **independent subprocess**. `MCPServerManager` helps you manage them uniformly:
```python
manager = MCPServerManager()

# Register configurations (only stores config, doesn't start)
manager.register_config(MCPServerConfig(name="asr", command=["python", "asr_server.py"]))
manager.register_config(MCPServerConfig(name="vad", command=["python", "vad_server.py"]))

# One-click start all
await manager.start_all()  # Start asr + vad two processes

# Get a client for a specific server and call the tool
asr_client = manager.get_client("asr")
result = await asr_client.call_tool("transcribe", {"audio_path": "test.wav"})

# One-click shutdown all
await manager.shutdown_all()
```

**Core Methods**:

| Method | Purpose |
|--------|---------|
| `register_config()` | Register server configuration (records only, doesn't start) |
| `start_all()` | Start all registered servers |
| `shutdown_all()` | Shutdown all running servers |
| `get_client()` | Get MCPClient for a specific server |
| `list_servers()` | List all registered server names |
| `list_running()` | List all currently running server names |

**Key Point**: `MCPClient` is responsible for communicating with **one** server, `MCPServerManager` is responsible for managing **multiple** `MCPClient`s.

---

### 7. `mcp/tool_adapter.py` - MCP Tool Adapter

**Purpose**: The **bridge** between the MCP world and the Agent world.

**Why need Adapter?**
```
MCP World                          Agent World
-------------------------------------------------
MCPTool (external process)         BaseTool (Python class)
  name                              spec.name
  description                       spec.description
  input_schema                      spec.input_schema
  call_tool() (async)               invoke() (sync)
-------------------------------------------------
```

MCP tools have their own names, descriptions, and parameter formats, but the Agent only understands the `BaseTool` interface. **Adapter translates MCP tools into BaseTool**.

**Three Core Translations**:

| MCP Side | Agent Side | Translation Method |
|----------|-----------|-------------------|
| `MCPTool.name` | `ToolSpec.name` | Direct copy |
| `MCPTool.description` | `ToolSpec.description` | Direct copy |
| `MCPTool.input_schema` | `ToolSpec.input_schema` | Direct copy |
| `MCPClient.call_tool()` (async) | `BaseTool.invoke()` (sync) | `asyncio.run()` bridge |

**`invoke()` Sync/Async Problem**:

Here is a **key design**:
```python
# BaseTool interface is synchronous
def invoke(self, request) -> ToolResult: ...

# MCPClient interface is asynchronous
async def call_tool(self, name, args) -> dict: ...
```

**How to bridge?**
```python
def invoke(self, request):
    # Call async method inside sync method
    result = asyncio.run(self._async_invoke(request))
    return result
```

`asyncio.run()` purpose: **Start a new event loop, run async code, return the result**.

Like having a Chinese-speaking friend and an English-speaking friend - the Adapter is the translator that lets them talk.

---

### 8. `catalog/loader.py` - MCP Tool Catalog Loader

**Purpose**: Automatically discovers and registers MCP tools from the `catalog/` directory.

**Core Flow**:
```python
# 1. Scan catalog/ directory
for each subdirectory:
    if config.yaml exists:
        read configuration

# 2. Register server configurations
server_manager.register_config(MCPServerConfig(...))

# 3. One-click start all servers
await server_manager.start_all()

# 4. Get tool list from each server
for each running server:
    tools = await client.list_tools()  # "What tools do you have?"

# 5. Register to Agent's Registry
for each tool:
    adapter = MCPToolAdapter(client, tool)
    registry.register(adapter)  # "Agent, this tool is available!"
```

**Expected Directory Structure**:
```
catalog/
├── asr_qwen3/
│   ├── config.yaml      <- loader looks for this file
│   ├── server.py
│   └── ...
├── diarizen/
│   ├── config.yaml
│   ├── server.py
│   └── ...
└── example_echo/
    ├── config.yaml
    ├── server.py
    └── ...
```

**`config.yaml` Format**:
```yaml
name: asr_qwen3
server:
  command: [".venv/bin/python", "server.py"]
  working_dir: "."
  env:
    MODEL_PATH: "/path/to/model"
```

**`loader.py` automatically reads these configurations, no need to manually register one by one!**

---

### 9. `catalog/_template/` - New Tool Template

**Purpose**: Template directory for creating new MCP tools.

**Files**:

| File | Purpose |
|------|---------|
| `config.yaml` | MCP server configuration |
| `pyproject.toml` | Python project dependencies |
| `server.py` | MCP server implementation (framework) |
| `setup.sh` | Create isolated environment script |
| `README.md` | Tool documentation template |

**`server.py` Core Structure**:
```python
for line in sys.stdin:           # Continuously read requests
    request = json.loads(line)   # Parse JSON-RPC
    method = request["method"]   # Determine request type
    
    if method == "tools/list":
        return tool list         # Tell Agent what tools I have
    elif method == "tools/call":
        return execution result  # Actually do the work
    elif method == "shutdown":
        break                    # Exit
```

**Key Point**: MCP server is an **infinite loop**, continuously reading requests from `stdin`, processing them, and writing responses to `stdout`.

---

### 10. `catalog/example_echo/` - Example Tool

**Purpose**: A working MCP tool example for testing the MCP infrastructure.

**Function**: Provides 1 tool: `echo`
- Input: `{"text": "hello"}`
- Output: `{"echoed_text": "hello"}`

**Why no setup.sh / pyproject.toml?**

Because it **has no external dependencies**, can run directly with system Python:
```bash
cd tools/catalog/example_echo
python server.py
```

Then manually enter JSON-RPC tests:
```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

**Difference from `_template/`**:

| | `_template/` | `example_echo/` |
|--|-------------|----------------|
| Purpose | Copy and modify into new tool | Run directly for testing |
| setup.sh | Yes (create virtual env) | No (zero dependencies) |
| server.py | Only framework, TODO comments | Complete echo implementation |

---

## Data Flow Diagram

### Tool Execution Complete Flow

```
Planner decides: call_tool "asr_transcribe"
        |
        v
+-----------------------------------------+
|  tool_executor_node                     |
|  1. Construct ToolCallRequest           |
|  2. executor.execute(request)           |
|     2a. registry.get("asr_transcribe")  |
|     2b. tool.validate_request()         |
|     2c. tool.invoke(request)            |
|         - If internal: direct execution |
|         - If MCP: client.call_tool()    |
|     2d. Return ToolResult               |
|  3. Store result in state               |
+-----------------------------------------+
        |
        v
  evidence_fusion_node
        |
        v
  planner_decision_node (next round)
```

### MCP Tool Complete Flow

```
Agent Startup:
  loader.scan_catalog()
    -> Find example_echo/config.yaml
    -> server_manager.register_config()
    -> server_manager.start_all()
       -> subprocess.Popen("python server.py")
    -> client.list_tools()
       -> "echo" tool
    -> MCPToolAdapter(client, echo_tool)
    -> registry.register(adapter)

Planner Decision:
  registry.list_specs()
    -> [ToolSpec("echo", "Echo the input...", ...)]
    -> Planner sees this tool

Tool Execution:
  executor.execute(request for "echo")
    -> registry.get("echo")
    -> adapter.invoke(request)
       -> asyncio.run(adapter._async_invoke())
          -> client.call_tool("echo", {"text": "hello"})
             -> Write to stdin: {"method":"tools/call",...}
             -> Read from stdout: {"result":{...}}
          -> Package as ToolResult
    -> Return ToolResult
```

---

## Usage Examples

### Register and Use Internal Tool
```python
from tools import ToolRegistry, ToolExecutor
from core.schemas import ToolSpec, ToolCallRequest, ToolResult
from tools.base import BaseTool

class CalculatorTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="calc", description="Add two numbers")
    
    def invoke(self, request: ToolCallRequest) -> ToolResult:
        a = request.args.get("a", 0)
        b = request.args.get("b", 0)
        return ToolResult(tool_name="calc", success=True, output={"sum": a + b})

registry = ToolRegistry()
registry.register(CalculatorTool())

executor = ToolExecutor(registry)
request = ToolCallRequest(tool_name="calc", args={"a": 3, "b": 5})
result = asyncio.run(executor.execute(request))
print(result.output)  # {"sum": 8}
```

### Auto-discover and Register MCP Tools
```python
from tools import ToolRegistry
from tools.mcp import MCPServerManager
from tools.catalog import register_all_mcp_tools

registry = ToolRegistry()
manager = MCPServerManager()

await register_all_mcp_tools(registry, manager, verbose=True)

# Now registry contains all MCP tools from catalog/
specs = registry.list_specs()
print([s.name for s in specs])  # ["echo", ...]
```

---

## Comparison with Original Project

| Item | Original AUDIO_AGENT | This Project agent-basic |
|------|---------------------|-------------------------|
| Tool Adapters | Qwen3-ASR, Diarizen, FFmpeg, Librosa, VAD, etc. | Only保留 MCP infrastructure + echo example |
| Tool Registration | Manual + auto-discovery | Unified via loader.py |
| MCP Client | Full JSON-RPC implementation | Simplified but complete |
| Server Manager | Complex lifecycle management | Simplified multi-server management |
| Tool Adapter | Adapts MCP to BaseTool | Same design, simplified |
| Catalog Structure | Complete tool implementations | Template + minimal example |

---

## Common Issues

### Q1: "Tool 'xxx' not found"
**Cause**: Tool not registered, or name mismatch.
**Solution**: Check `registry.register()` and `request.tool_name`.

### Q2: MCP server fails to start
**Cause**: Command error, missing dependencies, or port conflict.
**Solution**: Check `config.yaml` command and working_dir.

### Q3: JSON-RPC communication timeout
**Cause**: Server process hangs or crashes.
**Solution**: Test server manually: `python server.py`, then send requests manually.

### Q4: asyncio.run() cannot be called from a running event loop
**Cause**: Calling `adapter.invoke()` inside an async function.
**Solution**: Use `await adapter._async_invoke()` directly, or ensure invoke() is called from a sync context.

---

## Extension Guide

### How to Add a New MCP Tool

```bash
# 1. Copy template
cp -r tools/catalog/_template tools/catalog/my_tool

# 2. Edit config.yaml
cd tools/catalog/my_tool
# Modify name, command, etc.

# 3. Implement server.py
# Add your tool logic in handle_tool_call()

# 4. Create environment (if needed)
./setup.sh

# 5. Test
python server.py
# Manually send JSON-RPC requests
```

---

## Testing

Run tool tests:
```bash
cd agent-basic
D:\anaconda3\envs\agent-basic\python.exe tests\test_tools.py
```
