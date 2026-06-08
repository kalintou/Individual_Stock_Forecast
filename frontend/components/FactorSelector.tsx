"use client";

import type { FactorKey } from "@/lib/types";
import { factorDescriptions, factorLabels } from "@/lib/format";

interface FactorSelectorProps {
  selected: FactorKey[];
  onChange: (factors: FactorKey[]) => void;
}

const factors: FactorKey[] = ["technical", "fundamental", "capital", "sentiment"];

export function FactorSelector({ selected, onChange }: FactorSelectorProps) {
  function toggle(key: FactorKey) {
    if (selected.includes(key)) {
      onChange(selected.filter((item) => item !== key));
    } else {
      onChange([...selected, key]);
    }
  }

  return (
    <section className="card p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">选择分析因子</h2>
          <p className="mt-1 text-sm text-slate-500">默认四因子全部执行，也可以按本次问题只选择部分因子。</p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => onChange(factors)}>
          全选
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {factors.map((key) => {
          const checked = selected.includes(key);
          return (
            <label
              key={key}
              className={`cursor-pointer rounded-2xl border p-4 transition ${checked ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
            >
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(key)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <div>
                  <div className="font-semibold text-slate-900">{factorLabels[key]} <span className="text-xs text-slate-400">{key}</span></div>
                  <p className="mt-1 text-sm leading-6 text-slate-500">{factorDescriptions[key]}</p>
                </div>
              </div>
            </label>
          );
        })}
      </div>
      {selected.length === 0 ? <p className="mt-3 text-sm text-red-600">请至少选择一个分析因子。</p> : null}
    </section>
  );
}
