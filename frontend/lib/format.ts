import type { FactorKey } from "./types";

export const factorLabels: Record<FactorKey, string> = {
  technical: "技术面",
  fundamental: "基本面",
  capital: "资金面",
  sentiment: "情绪面",
};

export const factorDescriptions: Record<FactorKey, string> = {
  technical: "K线、均线、趋势、成交量、波动率",
  fundamental: "估值、财务质量、成长性、行业位置",
  capital: "主力资金、融资融券、资金流向",
  sentiment: "新闻、热点、人气、龙虎榜、催化事件",
};

export function scoreLevel(score?: number | null): string {
  if (score == null) return "暂无评分";
  if (score >= 80) return "强势";
  if (score >= 60) return "偏强";
  if (score >= 40) return "中性";
  return "偏弱";
}

export function strengthClass(score?: number | null): string {
  if (score == null) return "text-slate-500 bg-slate-50 border-slate-200";
  if (score >= 60) return "text-red-700 bg-red-50 border-red-100";
  if (score < 40) return "text-green-700 bg-green-50 border-green-100";
  return "text-slate-700 bg-slate-50 border-slate-200";
}

export function formatPercent(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value.toFixed(2)}%`;
}

export function formatNumber(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "--";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}
