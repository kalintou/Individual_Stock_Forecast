# Example Echo Tool

A minimal MCP tool for testing the MCP infrastructure.

## What it does

Provides a single tool `echo` that returns the input text unchanged.

## Run

No setup needed! Run directly:

```bash
python server.py
```

Then type JSON-RPC requests:

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

Expected response:
```json
{"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "echo", ...}]}}
```

## Test tool call

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "hello"}}}
```

Expected response:
```json
{"jsonrpc": "2.0", "id": 2, "result": {"success": true, "output": {"echoed_text": "hello"}}}
```
