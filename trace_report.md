# Agent Execution Trace

Generated: 2026-06-08T19:42:23.218794

Total nodes: 3

## 1. intent_clarification_node

- Timestamp: 2026-06-08T19:39:56.191946
- Elapsed: 147023.12 ms

### Output

```json
{
  "user_intent": {
    "stock_name": "贵州茅台",
    "stock_code": "",
    "intent_type": "analysis",
    "time_horizon": "long",
    "risk_preference": "moderate",
    "clarified_query": "请分析一下贵州茅台的短期、中期和长期表现。"
  }
}
```

## 2. market_structure_node

- Timestamp: 2026-06-08T19:42:23.216311
- Elapsed: 0.16 ms

### Output

```json
{
  "status": "failed",
  "error_message": "无法解析股票代码: 贵州茅台"
}
```

## 3. failure_node

- Timestamp: 2026-06-08T19:42:23.217284
- Elapsed: 0.24 ms

### Output

```json
{
  "error_message": "无法解析股票代码: 贵州茅台",
  "status": "failed"
}
```

