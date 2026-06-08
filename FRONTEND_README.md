# 个股智能分析系统 Web 前端与 FastAPI 后端

本次新增了一个 Next.js 前端和 FastAPI API 桥接层。前端不会接触 LLM API Key，所有模型调用仍由 Python 后端完成，并复用原有 LangGraph 工作流。

## 1. 后端启动

在项目根目录执行：

```bash
pip install -r requirements.txt
uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000
```

后端会读取项目根目录 `.env` 中的配置：

```bash
PLANNER_API_KEY=你的APIKey
PLANNER_BASE_URL=https://你的模型服务/v1
PLANNER_MODEL=gpt-4o
```

健康检查：

```bash
curl http://localhost:8000/api/health
```

返回：

```json
{"ok": true, "service": "stock-forecast-agent"}
```

## 2. 前端启动

```bash
cd frontend
npm install
npm run dev
```

新建或编辑 `frontend/.env.local`：

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

浏览器打开：

```bash
http://localhost:3000
```

## 3. API 接口

### GET /api/health

返回服务状态。

### POST /api/analyze

请求示例：

```json
{
  "query": "帮我分析一下贵州茅台",
  "selected_factors": ["technical", "fundamental", "capital", "sentiment"],
  "prompt_append": {
    "global": "请特别区分短期、中期、长期。",
    "capital_system": "资金面部分请重点分析主力资金连续性。"
  },
  "trace": true
}
```

### GET /api/prompts

返回 prompts 目录下默认 system prompt 的只读内容。前端只做 per-request append，不会覆盖原始 md 文件。

### GET /api/hot-stocks

返回东方财富 A 股人气股票榜，字段做了防御式解析，接口异常时返回空数组。

### GET /api/chart-data/{stock_code}

返回近期 K 线、估值与基础信息，用于前端图表。

## 4. 功能测试建议

1. 默认四因子分析：保持四个 checkbox 全选，输入“分析一下贵州茅台短期中期长期怎么看”，点击“开始分析”。
2. 只选技术面 + 资金面：取消“基本面”和“情绪面”，确认未选择卡片显示“未选择该因子，本次未纳入分析”。
3. 追加 system prompt：展开“高级设置：追加 System Prompt”，在“全局追加 prompt”中输入“请输出短期、中期、长期三个时间维度”，再次分析。
4. 查看 trace 折叠栏：分析中显示固定步骤，分析完成后显示真实节点、耗时、状态和输出摘要。
5. 查看热门人气股票：右侧“A 股人气股票”表格会调用 `/api/hot-stocks`，点击股票名会填入输入框，点击“分析该股”会直接分析。
6. 查看图表和表格：分析完成后查看因子评分柱状图、近期收盘价折线图、涨跌幅柱状图、估值表和证据记录表。

## 5. 已知限制

- `/api/analyze` 是同步调用，单次分析时间取决于 LLM 接口和行情数据接口响应速度。
- 东方财富、AkShare 等公开数据接口可能出现限流、字段变化或临时不可用，后端已尽量使用 fallback 和空状态避免崩溃。
- Trace 只展示执行轨迹摘要，不展示完整 prompt、输入状态、模型私有推理链或 API Key。
- 当前 prompt 追加仅在本次请求生效，不会保存到 `prompts/*.md`。
- 图表使用后端可获取的行情字段，若某个股票代码无法获取 K 线或估值，则前端显示“暂无图表数据”。

## UI 调整 v4

本版本新增/调整：

1. A 股人气股票表格去掉“市场”列，新增“最近涨幅”列；后端会尽量用 AkShare 实时 A 股行情补全真实股票名称和最近一个交易日涨跌幅。
2. 输入框下方的推荐问题已移除；四个因子选择压缩到输入区右上角，只保留“技术面 / 基本面 / 资金面 / 情绪面”四个选项。
3. 新增 `POST /api/analyze/stream` SSE 流式接口；前端点击“开始分析”后会实时接收节点 trace，节点完成后立即更新 Trace 折叠栏。该 trace 仅包含节点名、状态、耗时、摘要，不包含模型私有思维链。

如果部署到 Vercel + Render，请确保：

- Vercel 环境变量：`NEXT_PUBLIC_API_BASE=https://你的Render后端地址`
- Render 后端重新部署后包含 `/api/analyze/stream`
- 如果仍有跨域问题，后端已默认允许 `https://*.vercel.app`
