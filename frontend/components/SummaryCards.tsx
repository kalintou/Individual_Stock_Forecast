"use client";

import type { AnalyzeResponse, FactorKey } from "@/lib/types";
import { factorLabels, scoreLevel, strengthClass } from "@/lib/format";

interface SummaryCardsProps {
  result: AnalyzeResponse;
  selectedFactors: FactorKey[];
}

export function SummaryCards({ result, selectedFactors }: SummaryCardsProps) {
  const intent = result.user_intent;
  const composite = result.composite_assessment;
  const score = composite?.composite_score;

  return (
    <section className="grid gap-4 lg:grid-cols-4">
      <div className="card p-5 lg:col-span-1">
        <p className="text-sm text-slate-500">分析标的</p>
        <h2 className="mt-2 text-2xl font-bold text-slate-900">{intent?.stock_name || "--"}</h2>
        <p className="mt-1 text-sm text-slate-500">{intent?.stock_code || "未识别代码"}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {selectedFactors.map((key) => <span key={key} className="badge">{factorLabels[key]}</span>)}
        </div>
      </div>
      <div className="card p-5">
        <p className="text-sm text-slate-500">综合评分</p>
        <div className="mt-2 flex items-end gap-2">
          <span className="text-4xl font-bold text-slate-900">{score ?? "--"}</span>
          <span className="pb-1 text-sm text-slate-400">/100</span>
        </div>
        <span className={`mt-3 inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${strengthClass(score)}`}>{scoreLevel(score)}</span>
      </div>
      <div className="card p-5">
        <p className="text-sm text-slate-500">趋势与位置</p>
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate-500">趋势方向</span><span className="font-semibold text-slate-900">{composite?.trend_direction || "--"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">位置状态</span><span className="font-semibold text-slate-900">{composite?.position_status || "--"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">分析周期</span><span className="font-semibold text-slate-900">{intent?.time_horizon || "--"}</span></div>
        </div>
      </div>
      <div className="card p-5">
        <p className="text-sm text-slate-500">风险与置信度</p>
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate-500">风险等级</span><span className="font-semibold text-slate-900">{composite?.risk_level || "--"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">回答置信度</span><span className="font-semibold text-slate-900">{result.final_answer?.confidence ?? "--"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">状态</span><span className="font-semibold text-slate-900">{result.status}</span></div>
        </div>
      </div>
    </section>
  );
}
