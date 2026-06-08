# 个股预测智能体 (Individual Stock Forecast Agent)

基于 LangGraph + LLM 的 A 股个股分析预测系统。数据层使用 `curl_cffi` 直接调用东方财富 / 新浪财经 API，绕过 TLS 指纹检测与 IP 级封锁。

投资核心理念：**趋势 + 主线 + 龙头**。系统通过四大因子（技术/基本面/资金/情绪）对个股进行综合评估，输出结构化的投资建议报告。

---

## 系统流程

### 完整工作流

```
START
  │
  ▼
intent_clarification          ← 解析用户意图（股票名称/代码、分析类型、时间周期、风险偏好）
  │
  ▼
market_structure              ← 分析股票在当前市场格局中的定位（主线/龙头/后排）
  │
  ▼
sector_router                 ← 动态决策：分析哪几个因子（技术/基本面/资金/情绪）
  │
  ├──► technical_analysis     ← 技术面：K线、MA、成交量、支撑阻力
  │
  ├──► fundamental_analysis   ← 基本面：PE/PB、行业、市值、估值水平
  │
  ├──► capital_analysis       ← 资金面：主力资金流向、机构持仓、融资融券
  │
  ├──► sentiment_analysis     ← 情绪面：新闻舆情、板块热度、龙虎榜、事件催化
  │
  ▼
cross_sector_fusion           ← 综合四因子证据，输出统一评估（趋势方向/位置状态/风险等级/综合评分）
  │
  ▼
final_answer                  ← 生成结构化中文报告
  │
  ▼
END
```

### 节点说明

| 节点 | 数据来源 | LLM 作用 |
|------|---------|---------|
| intent_clarification | 用户 query | 提取股票名称、代码、分析类型、时间周期 |
| market_structure | 个股信息 + K线 + 热点板块 | 判断股票在当前市场主线中的位置 |
| sector_router | 用户意图 + 市场结构 | 决策分析哪些因子（可跳过不相关因子） |
| technical_analysis | 历史K线 + 代码计算MA | 定性判断技术形态和趋势 |
| fundamental_analysis | 财务分析指标 + 个股信息 + 实时估值(PE/PB) | 基于 Python 计算的财报指标做定性解读 |
| capital_analysis | 个股资金流向 + 资金排行 | 判断主力资金态度 |
| sentiment_analysis | 个股新闻 + 热点板块 + 龙虎榜 + 人气排名 | 评估市场情绪和舆论氛围 |
| cross_sector_fusion | 四因子 Evidence | 加权综合评分，统一投资判断 |
| final_answer | 全部证据 | 生成结构化中文报告 |

**设计特点**：
- 每个因子节点都是"自包含"的——自己拉取数据、代码计算基础指标、格式化文本后调用 LLM 做定性判断
- 所有节点都有 try-except 兜底，任何单点失败不会导致整个流程崩溃
- 数据层使用 `curl_cffi` + CDN 节点轮换，直接调用东方财富 / 新浪财经 API，绕过 TLS 指纹检测

---

## 环境配置

### 1. 创建 Conda 环境

```bash
# 克隆已有环境（推荐，已预装所有依赖）
conda create --name stock-forecast-agent --clone agent-basic

# 或从头创建
conda create -n stock-forecast-agent python=3.11
conda activate stock-forecast-agent
pip install -r requirements.txt
```

### 2. 安装 `curl_cffi`（数据获取核心依赖）

```bash
conda activate stock-forecast-agent
pip install curl_cffi==0.15.0
```

`curl_cffi` 用于模拟浏览器 TLS 指纹（`impersonate="chrome120"`），直接调用东方财富 / 新浪财经 API，绕过 akshare 面临的 TLS 指纹检测和 IP 级封锁。

### 3. 安装 akshare（股票名称缓存，可选）

```bash
conda activate stock-forecast-agent
pip install akshare==1.18.60
```

akshare 目前仅用于**股票名称 → 代码映射缓存**（`_load_stock_name_cache`），实际行情/财务/资金数据均通过 `curl_cffi` 直接获取。

### 4. 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
copy .env.example .env
```

编辑 `.env`，填入你的 LLM API 信息：

```ini
# 必需
PLANNER_API_KEY=sk-your-api-key-here
PLANNER_BASE_URL=https://api.your-provider.com/v1

# 可选（默认 gpt-4o）
PLANNER_MODEL=gpt-4o

# 可选
MAX_STEPS=10
```

**支持的 API 格式**：任何 OpenAI-compatible 接口（如 OpenAI、Azure OpenAI、第三方代理等）。

---

## 运行方式

### 方式一：使用 .env 配置（推荐）

`.env` 中已配置好 API key 时，只需提供 `--query`：

```bash
conda activate stock-forecast-agent
python main.py --query "帮我看看贵州茅台怎么样"
```

### 方式二：命令行传入全部参数

```bash
conda activate stock-forecast-agent
python main.py \
  --query "帮我看看贵州茅台怎么样" \
  --planner-api-key sk-xxx \
  --planner-base-url https://api.xxx/v1 \
  --planner-model gpt-4o
```

### 方式三：带 Trace 运行（记录每步输入输出，方便调试）

```bash
conda activate stock-forecast-agent
python main.py --query "分析一下宁德时代" --trace
```

运行后会在当前目录生成 `trace.jsonl` 和 `trace_report.md` 文件。

### 不同场景的 query 示例

```bash
# 全面分析（默认四因子全开）
python main.py --query "帮我看看贵州茅台怎么样"

# 短线交易（sector_router 会自动侧重技术+资金+情绪）
python main.py --query "明天茅台能买吗"

# 长期价值（sector_router 会自动侧重基本面+技术趋势）
python main.py --query "贵州茅台值得长期持有吗"

# 风险排查
python main.py --query "宁德时代有没有暴雷风险"
```

### 输出示例

系统会输出一份**全中文**结构化报告，包含：
- 用户意图解析
- 市场结构定位（主线/龙头判断）
- 四大因子分析（评分 + 关键发现 + 风险标记）
- 综合评估（趋势方向 / 位置状态 / 风险等级 / 综合评分）
- 证据记录

> **语言要求**：所有 system prompt 均强制要求 LLM 面向读者的字段（`key_findings`、`risk_flags`、`raw_data_summary`、`summary`、`risk_details` 等）必须使用**简体中文**，禁止出现英文句子。

---

## 数据获取架构

### 数据源映射

| 数据类型 | 原方案 | 现方案 | 说明 |
|---------|--------|--------|------|
| 个股基本信息 | akshare | `curl_cffi` → Eastmoney `stock/get` | 10 个 CDN 节点轮换 |
| 历史K线 | akshare | `curl_cffi` → Eastmoney `push2his` | 4 个 CDN 节点轮换 |
| 实时估值(PE/PB) | akshare | `curl_cffi` → Eastmoney `stock/get` | 提取 f162/f167/f168 等字段 |
| 热点概念板块 | akshare | `curl_cffi` → Sina Finance `newFLJK.php` | 175 个概念，稳定 |
| 行业板块行情 | akshare | `curl_cffi` → Sina Finance `newFLJK.php` | 84 个行业，稳定 |
| 龙虎榜数据 | akshare | `curl_cffi` → Eastmoney Datacenter | `RPT_DAILYBILLBOARD_DETAILSNEW` |
| 个股人气排名 | akshare | `curl_cffi` → Eastmoney `emappdata` | POST API |
| 资金流向排行 | akshare | `curl_cffi` → Eastmoney `clist/get` + fallback | CDN 轮换，失败则回退到历史数据聚合 |
| 个股资金流向 | akshare | `curl_cffi` → Eastmoney `data.eastmoney.com` | 始终可用 |
| 股票名称缓存 | akshare | akshare `stock_info_a_code_name` | 仅用于名称→代码映射 |

### 为什么不用 akshare 直接获取行情数据？

东方财富对 akshare 的默认请求进行了**TLS 指纹检测**和**IP 级封锁**：
- `*.push2.eastmoney.com` 的 `clist/get` 批量列表接口在当前 IP 已被完全封锁
- 单股接口（`stock/get`、`kline/get`）虽可用，但存在间歇性阻断

**解决方案**：使用 `curl_cffi` 模拟 Chrome TLS 指纹，直接调用 Eastmoney API，并通过多个 CDN 节点（`1.push2`、`11.push2`、`71.push2` 等）进行轮换，提升可用性。对于已被完全封锁的批量接口（`clist/get`），系统已永久迁移到**新浪财经**的板块数据 API。

---

## 运行测试

### 全部测试

```bash
conda activate stock-forecast-agent

# Phase 1 测试（意图解析 + 市场结构 + 最终报告）
python tests/test_phase1.py

# Phase 2 测试（完整四因子流程 + 路由跳过 + 数据获取）
python tests/test_phase2.py
```

### 测试说明

| 测试文件 | 内容 | 是否调用真实 API |
|---------|------|----------------|
| `tests/test_phase1.py` | Phase 1 完整流程 + 数据获取 | ❌ 使用 MockPlanner |
| `tests/test_phase2.py` | Phase 2 完整流程 + 路由跳过测试 + 数据获取 | ❌ 使用 MockPlanner |

测试使用 `MockPlanner` 模拟 LLM 响应，**不需要真实 API key**，用于验证：
- 数据接口（`curl_cffi` 直接调用）是否正常
- LangGraph 工作流节点是否正确串联
- state 传递和 schema 解析是否正确
- sector_router 的跳过/执行逻辑是否正常

---

## 项目结构

```
.
├── main.py                          # CLI 入口
├── config.py                        # 配置管理（.env + CLI 参数）
├── requirements.txt                 # Python 依赖
├── capital_factor.py                # 资金面因子模块（curl_cffi 直接调用 Eastmoney API）
├── .env                             # API 配置（需手动创建）
├── .env.example                     # 配置模板
│
├── core/                            # 核心模块
│   ├── schemas.py                   # Pydantic 数据模型（UserIntent/MarketStructure/FactorEvidence/...）
│   ├── state.py                     # LangGraph AgentState 定义
│   ├── constants.py                 # 常量枚举
│   ├── errors.py                    # 异常定义
│   ├── logging.py                   # 日志工具
│   └── README.md
│
├── graph/                           # LangGraph 工作流
│   ├── nodes.py                     # 所有节点函数（Phase 1 + Phase 2，数据层使用 curl_cffi）
│   ├── builder.py                   # 图构建与编译
│   ├── trace.py                     # Trace 记录工具
│   └── README.md
│
├── planner/                         # LLM 规划器
│   ├── base.py                      # 抽象基类
│   ├── openai_compatible_planner.py # OpenAI-compatible 实现
│   └── README.md
│
├── prompts/                         # Prompt 模板（均含简体中文强制要求）
│   ├── intent_system.md             # 意图解析 System Prompt
│   ├── intent_user.md               # 意图解析 User Prompt 模板
│   ├── market_structure_*.md        # 市场结构分析 Prompt
│   ├── sector_route_*.md            # 因子路由决策 Prompt
│   ├── technical_*.md               # 技术面分析 Prompt
│   ├── fundamental_*.md             # 基本面分析 Prompt
│   ├── capital_*.md                 # 资金面分析 Prompt
│   ├── sentiment_system.md          # 情绪面 System Prompt（通用回退）
│   ├── sentiment_short_term.md      # 情绪面短期分支 Prompt
│   ├── sentiment_long_term.md       # 情绪面中长期分支 Prompt
│   ├── sentiment_user.md            # 情绪面 User Prompt 模板
│   └── fusion_*.md                  # 跨因子融合 Prompt
│
├── fusion/                          # 证据融合模块
│   ├── base.py                      # 融合抽象基类
│   ├── simple_fusion.py             # 简单融合实现
│   └── README.md
│
├── tools/                           # 工具模块（MCP 工具框架）
│   ├── base.py
│   ├── executor.py
│   ├── registry.py
│   ├── catalog/                     # 工具目录
│   └── mcp/                         # MCP 客户端/服务端
│
├── tests/                           # 测试
│   ├── test_phase1.py               # Phase 1 集成测试
│   ├── test_phase2.py               # Phase 2 集成测试
│   ├── test_capital_workflow_contract.py
│   └── total-real-test/             # 真实 API 端到端测试
│
└── docs/
    └── capital_factor_skill.md      # 资金面因子技术文档
```

---

## 关键依赖版本

```
Python 3.11.15
langgraph==1.1.10
openai==2.33.0
pydantic==2.13.3
python-dotenv==1.2.2
curl_cffi==0.15.0      # 核心：绕过 TLS 指纹检测
akshare==1.18.60       # 仅用于股票名称缓存
```

---

## 网络与代理配置

如果你在使用系统代理（如 Clash、V2Ray），可能会遇到东方财富 API 连接问题：

```bash
# 在运行前设置 no_proxy，避免代理干扰直连 Eastmoney CDN
set NO_PROXY=*
# 或针对 Eastmoney 域名
set NO_PROXY=*.eastmoney.com,*.sina.com.cn
```

代码中关键数据获取函数已内置 `os.environ.setdefault("NO_PROXY", "*")` 以自动绕过代理。

---

## 注意事项

1. **免责声明**：本系统输出仅供参考，不构成投资建议。股市有风险，投资需谨慎。
2. **数据延迟**：通过 `curl_cffi` 获取的数据与东方财富网页版一致，可能存在分钟级延迟。
3. **IP 封锁**：`clist/get` 等批量列表接口在部分 IP 段已被东方财富完全封锁，系统已自动回退到新浪财经数据源或历史数据聚合方案。

---

## License

MIT
