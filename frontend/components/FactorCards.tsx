"use client";

import type { AnalyzeResponse, FactorKey, FactorEvidence } from "@/lib/types";
import { factorDescriptions, factorLabels, scoreLevel, strengthClass } from "@/lib/format";

interface FactorCardsProps {
  result: AnalyzeResponse;
  selectedFactors: FactorKey[];
}

const factorKeys: FactorKey[] = ["technical", "fundamental", "capital", "sentiment"];

function EvidenceList({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-500">{title}</p>
      <ul className="space-y-1 text-sm text-slate-600">
        {items.map((item, index) => <li key={`${title}-${index}`}>• {item}</li>)}
      </ul>
    </div>
  );
}

function FactorCard({ factorKey, evidence, selected }: { factorKey: FactorKey; evidence?: FactorEvidence | null; selected: boolean }) {
  if (!selected || !evidence) {
    return (
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-900">{factorLabels[factorKey]}</h3>
            <p className="mt-1 text-sm text-slate-500">{factorDescriptions[factorKey]}</p>
          </div>
          <span className="badge">未执行</span>
        </div>
        <p className="mt-5 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">未选择该因子，本次未纳入分析。</p>
      </div>
    );
  }

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold text-slate-900">{factorLabels[factorKey]}</h3>
          <p className="mt-1 text-sm text-slate-500">{factorDescriptions[factorKey]}</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-sm font-semibold ${strengthClass(evidence.score)}`}>{evidence.score} · {scoreLevel(evidence.score)}</span>
      </div>
      <div className="mt-4 space-y-4">
        <div className="rounded-xl bg-slate-50 p-3 text-sm text-slate-700">趋势信号：<span className="font-semibold text-slate-900">{evidence.trend_signal || "--"}</span></div>
        <EvidenceList title="关键发现" items={evidence.key_findings} />
        <EvidenceList title="风险提示" items={evidence.risk_flags} />
        <div>
          <p className="mb-1 text-xs font-semibold text-slate-500">原始数据摘要</p>
          <p className="whitespace-pre-wrap text-sm leading-6 text-slate-600">{evidence.raw_data_summary || "暂无摘要"}</p>
        </div>
      </div>
    </div>
  );
}

export function FactorCards({ result, selectedFactors }: FactorCardsProps) {
  return (
    <section className="grid gap-4 lg:grid-cols-2">
      {factorKeys.map((key) => (
        <FactorCard key={key} factorKey={key} evidence={result.factors?.[key]} selected={selectedFactors.includes(key)} />
      ))}
    </section>
  );
}
