"use client";

import type { AnalyzeResponse } from "@/lib/types";

interface MarketStructureCardProps {
  result: AnalyzeResponse;
}

function valueToText(value: unknown): string {
  if (Array.isArray(value)) return value.join("、") || "--";
  if (value == null || value === "") return "--";
  return String(value);
}

export function MarketStructureCard({ result }: MarketStructureCardProps) {
  const market = result.market_structure || {};
  const rows = [
    ["当前市场主线", market.current_market_themes],
    ["股票所属主线", market.stock_themes],
    ["主线内位置", market.theme_position],
    ["市场情绪", market.market_sentiment],
    ["板块热度排名", market.sector_heat_rank],
    ["分析摘要", market.analysis_summary],
  ];

  return (
    <section className="card p-5">
      <h2 className="mb-4 text-base font-semibold text-slate-900">市场结构定位</h2>
      <div className="overflow-hidden rounded-2xl border border-slate-200">
        <table className="w-full text-sm">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label as string} className="border-b border-slate-100 last:border-0">
                <td className="w-36 bg-slate-50 px-4 py-3 font-medium text-slate-600">{label as string}</td>
                <td className="px-4 py-3 leading-6 text-slate-800">{valueToText(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
