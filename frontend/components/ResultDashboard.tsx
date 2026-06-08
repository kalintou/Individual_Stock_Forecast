"use client";

import type { AnalyzeResponse, FactorKey } from "@/lib/types";
import { SummaryCards } from "./SummaryCards";
import { FactorCards } from "./FactorCards";
import { ChartSection } from "./ChartSection";
import { MarketStructureCard } from "./MarketStructureCard";

interface ResultDashboardProps {
  result: AnalyzeResponse;
  selectedFactors: FactorKey[];
}

export function ResultDashboard({ result, selectedFactors }: ResultDashboardProps) {
  return (
    <div className="space-y-5">
      <SummaryCards result={result} selectedFactors={selectedFactors} />
      <FactorCards result={result} selectedFactors={selectedFactors} />
      <ChartSection result={result} />
      <MarketStructureCard result={result} />
      <section className="card p-5">
        <h2 className="mb-4 text-base font-semibold text-slate-900">完整 AI 报告</h2>
        <pre className="whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">{result.final_answer?.answer || "暂无报告"}</pre>
      </section>
      <section className="card p-5">
        <h2 className="mb-4 text-base font-semibold text-slate-900">证据记录</h2>
        {result.evidence_log?.length ? (
          <div className="overflow-auto rounded-2xl border border-slate-200">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3">source</th>
                  <th className="px-4 py-3">score</th>
                  <th className="px-4 py-3">confidence</th>
                  <th className="px-4 py-3">content</th>
                  <th className="px-4 py-3">timestamp</th>
                </tr>
              </thead>
              <tbody>
                {result.evidence_log.map((item, index) => (
                  <tr key={`${item.source}-${index}`} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-medium text-slate-800">{String(item.source ?? "--")}</td>
                    <td className="px-4 py-3 text-slate-600">{String(item.score ?? "--")}</td>
                    <td className="px-4 py-3 text-slate-600">{String(item.confidence ?? "--")}</td>
                    <td className="px-4 py-3 leading-6 text-slate-600">{String(item.content ?? "--")}</td>
                    <td className="px-4 py-3 text-slate-500">{String(item.timestamp ?? "--")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-400">暂无证据记录</p>}
      </section>
    </div>
  );
}
