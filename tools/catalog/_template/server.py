"""
Template MCP server.

This is a minimal MCP server that implements the required handlers:
- initialize: Server initialization
- tools/list: Return available tools
- tools/call: Execute a tool
- shutdown: Cleanup

To customize:
1. Copy this directory
2. Rename the tool in config.yaml
3. Add your tool logic in handle_tool_call()
4. Update input_schema in handle_tools_list()
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
    send_response(request_id, result={"status": "ok"})


def handle_tools_list(request_id, params):
    """Handle tools/list request."""
    tools = [
        {
            "name": "my_tool",
            "description": "A template tool that does something useful",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input parameter"
                    }
                },
                "required": ["input"]
            }
        }
    ]
    send_response(request_id, result={"tools": tools})


def handle_tool_call(request_id, params):
    """Handle tools/call request."""
    name = params.get("name")
    arguments = params.get("arguments", {})
    
    # TODO: Implement your tool logic here
    result = {"output": f"Processed: {arguments}"}
    
    send_response(request_id, result=result)


def handle_shutdown(request_id, params):
    """Handle shutdown request."""
    send_response(request_id, result={"status": "shutting_down"})


def main():
    """Main loop: read requests from stdin, write responses to stdout."""
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
            send_response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
