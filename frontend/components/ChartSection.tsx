"use client";

import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchChartData } from "@/lib/api";
import type { AnalyzeResponse, ChartDataResponse, KlinePoint } from "@/lib/types";
import { formatNumber, formatPercent } from "@/lib/format";

interface ChartSectionProps {
  result: AnalyzeResponse;
}

export function ChartSection({ result }: ChartSectionProps) {
  const stockCode = result.user_intent?.stock_code;
  const [chartData, setChartData] = useState<ChartDataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const initialKline = result.charts?.kline || [];
  const factorScores = result.charts?.factor_scores || [];

  useEffect(() => {
    if (!stockCode) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchChartData(stockCode)
      .then((data) => { if (!cancelled) setChartData(data); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "图表数据获取失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [stockCode]);

  const kline: KlinePoint[] = useMemo(() => chartData?.kline?.length ? chartData.kline : initialKline, [chartData, initialKline]);

  return (
    <section className="card p-5">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">图表与行情数据</h2>
          <p className="mt-1 text-sm text-slate-500">因子评分、近期收盘价、涨跌幅与估值概览。</p>
        </div>
        {loading ? <span className="badge">图表加载中...</span> : null}
      </div>
      {error ? <p className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-700">{error}</p> : null}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">因子评分柱状图</h3>
          {factorScores.length ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={factorScores}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Bar dataKey="score" fill="#ef4444" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyChart />}
        </div>

        <div className="rounded-2xl border border-slate-200 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">近期 K 线收盘价</h3>
          {kline.length ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={kline}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" minTickGap={20} />
                  <YAxis domain={["auto", "auto"]} />
                  <Tooltip formatter={(value) => formatNumber(Number(value))} />
                  <Line type="monotone" dataKey="close" stroke="#0f172a" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyChart />}
        </div>

        <div className="rounded-2xl border border-slate-200 p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-800">涨跌幅柱状图</h3>
          {kline.length ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={kline}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" minTickGap={20} />
                  <YAxis />
                  <Tooltip formatter={(value) => formatPercent(Number(value))} />
                  <Bar dataKey="pct_change" fill="#ef4444" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyChart />}
        </div>
      </div>

      {chartData?.valuation ? (
        <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200">
          <table className="w-full text-sm">
            <tbody>
              {Object.entries(chartData.valuation).map(([key, value]) => (
                <tr key={key} className="border-b border-slate-100 last:border-0">
                  <td className="bg-slate-50 px-4 py-3 font-medium text-slate-600">{key}</td>
                  <td className="px-4 py-3 text-slate-800">{String(value ?? "--")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function EmptyChart() {
  return <div className="flex h-72 items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-400">暂无图表数据</div>;
}
