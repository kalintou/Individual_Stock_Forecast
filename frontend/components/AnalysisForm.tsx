"use client";

import { Loader2, Search } from "lucide-react";
import type { FactorKey } from "@/lib/types";
import { factorLabels } from "@/lib/format";

interface AnalysisFormProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  error?: string | null;
  selectedFactors: FactorKey[];
  onFactorsChange: (factors: FactorKey[]) => void;
}

const factors: FactorKey[] = ["technical", "fundamental", "capital", "sentiment"];

export function AnalysisForm({
  query,
  onQueryChange,
  onSubmit,
  loading,
  error,
  selectedFactors,
  onFactorsChange,
}: AnalysisFormProps) {
  function toggleFactor(key: FactorKey) {
    if (selectedFactors.includes(key)) {
      onFactorsChange(selectedFactors.filter((item) => item !== key));
    } else {
      onFactorsChange([...selectedFactors, key]);
    }
  }

  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <label className="block text-sm font-semibold text-slate-800">股票 / 问题输入</label>
        {/* <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-medium text-slate-500">分析因子</span>
          {factors.map((key) => {
            const checked = selectedFactors.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleFactor(key)}
                className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                  checked
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                }`}
              >
                {factorLabels[key]}
              </button>
            );
          })}
        </div> */}
      </div>

      <div className="flex flex-col gap-3 lg:flex-row">
        <textarea
          className="input min-h-[92px] flex-1 resize-none"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="请输入股票代码、股票名称或分析问题，例如：分析一下 贵州茅台（600519）"
        />
        <button className="btn-primary h-fit lg:min-w-32" onClick={onSubmit} disabled={loading}>
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
          {loading ? "分析中..." : "开始分析"}
        </button>
      </div>

      {selectedFactors.length === 0 ? <p className="mt-3 text-sm text-red-600">请至少选择一个分析因子。</p> : null}
      {error ? <p className="mt-3 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}
    </section>
  );
}
