"use client";

import { useEffect, useState } from "react";
import { Flame } from "lucide-react";
import { fetchHotStocks } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { HotStock } from "@/lib/types";

interface HotStocksTableProps {
  onSelectStock: (stock: HotStock, autoAnalyze?: boolean) => void;
}

function pctClass(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "text-slate-400";
  if (value > 0) return "font-semibold text-red-600";
  if (value < 0) return "font-semibold text-green-600";
  return "font-semibold text-slate-500";
}

export function HotStocksTable({ onSelectStock }: HotStocksTableProps) {
  const [stocks, setStocks] = useState<HotStock[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchHotStocks(30)
      .then((data) => { if (!cancelled) setStocks(data); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "热门股票获取失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="card p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Flame className="h-5 w-5 text-red-500" />
          <h2 className="text-base font-semibold text-slate-900">A 股人气股票</h2>
        </div>
        {loading ? <span className="badge">加载中...</span> : null}
      </div>
      {error ? <p className="mb-3 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-700">{error}</p> : null}
      {stocks.length === 0 && !loading ? <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-400">暂无人气股票数据</p> : null}
      {stocks.length ? (
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-xs text-slate-500">
              <tr className="border-b border-slate-100">
                <th className="py-2 pr-2">排名</th>
                <th className="py-2 pr-2">股票代码</th>
                <th className="py-2 pr-2">股票名称</th>
                <th className="py-2 pr-2 text-right">最近涨幅</th>
                <th className="py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((stock) => (
                <tr key={stock.raw_code || stock.code} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="py-3 pr-2 font-medium text-slate-700">{stock.rank}</td>
                  <td className="py-3 pr-2 text-slate-600">{stock.code}</td>
                  <td className="py-3 pr-2 font-semibold text-slate-900">
                    <button className="hover:underline" onClick={() => onSelectStock(stock, false)}>{stock.name || stock.code}</button>
                  </td>
                  <td className={`py-3 pr-2 text-right ${pctClass(stock.pct_change)}`}>{formatPercent(stock.pct_change)}</td>
                  <td className="py-3 text-right">
                    <button type="button" className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-white" onClick={() => onSelectStock(stock, true)}>
                      分析该股
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
