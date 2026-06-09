"use client";

import { useState } from "react";
import { BarChart3 } from "lucide-react";
import { analyzeStockStream } from "@/lib/api";
import type { AnalyzeResponse, FactorKey, HotStock } from "@/lib/types";
import { AnalysisForm } from "@/components/AnalysisForm";
import { PromptEditor, type PromptAppendState } from "@/components/PromptEditor";
import { TraceBar } from "@/components/TraceBar";
import { ResultDashboard } from "@/components/ResultDashboard";
import { HotStocksTable } from "@/components/HotStocksTable";
import { Disclaimer } from "@/components/Disclaimer";

const defaultFactors: FactorKey[] = ["technical", "fundamental", "capital", "sentiment"];
const defaultPromptAppend: PromptAppendState = {
  global: "",
  technical_system: "",
  fundamental_system: "",
  capital_system: "",
  sentiment_system: "",
  fusion_system: "",
};

function cleanPromptAppend(value: PromptAppendState): Record<string, string> {
  return Object.fromEntries(Object.entries(value).filter(([, text]) => text.trim().length > 0));
}

export default function Page() {
  const [query, setQuery] = useState("分析一下 贵州茅台（600519）");
  const [selectedFactors, setSelectedFactors] = useState<FactorKey[]>(defaultFactors);
  const [promptAppend, setPromptAppend] = useState<PromptAppendState>(defaultPromptAppend);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [liveTrace, setLiveTrace] = useState<AnalyzeResponse["trace"]>([]);
  const [lastSelectedFactors, setLastSelectedFactors] = useState<FactorKey[]>(defaultFactors);

  async function submit(overrideQuery?: string) {
    const finalQuery = (overrideQuery ?? query).trim();
    if (!finalQuery) {
      setError("请输入股票代码、股票名称或分析问题。");
      return;
    }
    if (selectedFactors.length === 0) {
      setError("请至少选择一个分析因子。");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    setLiveTrace([]);
    setLastSelectedFactors(selectedFactors);
    try {
      const data = await analyzeStockStream({
        query: finalQuery,
        selected_factors: selectedFactors,
        prompt_append: cleanPromptAppend(promptAppend),
        trace: true,
      }, {
        onTrace: setLiveTrace,
        onStatus: () => undefined,
      });
      setResult(data);
      if (data.error_message) {
        setError(data.error_message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "分析请求失败");
    } finally {
      setLoading(false);
    }
  }

  function handleSelectHotStock(stock: HotStock, autoAnalyze?: boolean) {
    const nextQuery = `分析一下 ${stock.name}（${stock.code}）`;
    setQuery(nextQuery);
    if (autoAnalyze) {
      void submit(nextQuery);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-8 lg:px-8">
        <header className="mb-6 flex flex-col justify-between gap-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-card lg:flex-row lg:items-center">
          <div className="flex items-start gap-4">
            <div className="rounded-2xl bg-slate-900 p-3 text-white"><BarChart3 className="h-6 w-6" /></div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-950">个股智能分析系统</h1>
              <p className="mt-2 text-sm text-slate-500">基于技术面、基本面、资金面、情绪面的 A 股多因子智能分析</p>
            </div>
          </div>
          <div className="rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700">
            数据仅供研究参考，不构成投资建议
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
          <div className="space-y-5">
            <AnalysisForm
              query={query}
              onQueryChange={setQuery}
              onSubmit={() => void submit()}
              loading={loading}
              error={error}
              selectedFactors={selectedFactors}
              onFactorsChange={setSelectedFactors}
            />
            <PromptEditor value={promptAppend} onChange={setPromptAppend} />
            <TraceBar trace={loading ? liveTrace : result?.trace || liveTrace} loading={loading} />
            {result ? <ResultDashboard result={result} selectedFactors={lastSelectedFactors} /> : null}
          </div>
          <aside className="space-y-5">
            <HotStocksTable onSelectStock={handleSelectHotStock} />
          </aside>
        </div>
        <Disclaimer />
      </div>
    </main>
  );
}
