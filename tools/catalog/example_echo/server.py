"""
Example MCP server: Echo tool.

This is a minimal but complete MCP server that can be used to test
the MCP infrastructure. It provides a single tool:
- echo: Returns the input text unchanged.

No external dependencies needed. Run directly with system Python.
"""

import json
import sys


def send_response(response_id, result=None, error=None):
    """Send a JSON-RPC response."""
    response = {"jsonrpc": "2.0", "id": response_id}
    if result is not None:
        response["result"] = result
    if error is not None:
        response["error"] = error
    print(json.dumps(response), flush=True)


def handle_initialize(request_id, params):
    """Handle initialize request."""
    send_response(request_id, result={"status": "ok", "server": "example_echo"})


def handle_tools_list(request_id, params):
    """Handle tools/list request."""
    tools = [
        {
            "name": "echo",
            "description": "Echo the input text back unchanged",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to echo"
                    }
                },
                "required": ["text"]
            }
        }
    ]
    send_response(request_id, result={"tools": tools})


def handle_tool_call(request_id, params):
    """Handle tools/call request."""
    name = params.get("name")
    arguments = params.get("arguments", {})
    
    if name == "echo":
        text = arguments.get("text", "")
        result = {
            "success": True,
            "output": {"echoed_text": text}
        }
    else:
        result = {
            "success": False,
            "error": f"Unknown tool: {name}"
        }
    
    send_response(request_id, result=result)


def handle_shutdown(request_id, params):
    """Handle shutdown request."""
    send_response(request_id, result={"status": "shutting_down"})


def main():
    """Main loop: read JSON-RPC requests from stdin."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        
        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})
        
        if method == "initialize":
            handle_initialize(request_id, params)
        elif method == "tools/list":
            handle_tools_list(request_id, params)
        elif method == "tools/call":
            handle_tool_call(request_id, params)
        elif method == "shutdown":
            handle_shutdown(request_id, params)
            break
        else:
            send_response(
                request_id,
                error={"code": -32601, "message": f"Method not found: {method}"}
            )


if __name__ == "__main__":
    main()
