# Capital Factor Skill

## 1. Module Objective

The Capital Factor Skill is designed to analyze the capital-flow condition of an A-share individual stock.

It aims to identify whether the stock currently shows signs of:

- Main-force capital inflow
- Main-force capital outflow
- Main-force accumulation
- Main-force distribution
- Retail chasing or retail takeover risk
- Capital-flow divergence
- Active margin financing participation
- Leverage-related capital risk

This module serves the main workflow of the **Individual Stock Intelligent Analysis** system and outputs a standardized `FactorEvidence` object for the `cross_sector_fusion` node.

---

## 2. Input

The capital factor module reads the following fields from `AgentState`:

| Field | Description |
|---|---|
| stock_code | Stock code, such as 600519, 300750, 000001 |
| stock_name | Stock name, such as Kweichow Moutai, CATL, Ping An Bank |
| user_intent | User intent, such as analysis / short_term_trade / long_term_invest / risk_check |
| time_horizon | Analysis horizon, such as short / medium / long |
| market_structure | Market structure information, optional |

---

## 3. Output

The module returns:

```python
{
    "capital_evidence": FactorEvidence,
    "evidence_log": [...]
}