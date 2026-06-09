"use client";

import { useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import { fetchPrompts } from "@/lib/api";

export type PromptAppendState = {
  global: string;
  technical_system: string;
  fundamental_system: string;
  capital_system: string;
  sentiment_system: string;
  fusion_system: string;
};

interface PromptEditorProps {
  value: PromptAppendState;
  onChange: (value: PromptAppendState) => void;
}

const tabs: { key: keyof PromptAppendState; label: string }[] = [
  { key: "global", label: "全局追加 prompt" },
  { key: "technical_system", label: "技术面 prompt 追加" },
  { key: "fundamental_system", label: "基本面 prompt 追加" },
  { key: "capital_system", label: "资金面 prompt 追加" },
  { key: "sentiment_system", label: "情绪面 prompt 追加" },
  { key: "fusion_system", label: "综合融合 prompt 追加" },
];

export function PromptEditor({ value, onChange }: PromptEditorProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<keyof PromptAppendState>("global");
  const [defaultPrompts, setDefaultPrompts] = useState<Record<string, string> | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  async function loadDefaults() {
    setLoadingPreview(true);
    setPreviewError(null);
    try {
      setDefaultPrompts(await fetchPrompts());
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "默认 prompt 获取失败");
    } finally {
      setLoadingPreview(false);
    }
  }

  function update(key: keyof PromptAppendState, text: string) {
    onChange({ ...value, [key]: text });
  }

  return (
    <section className="card p-5">
      <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setOpen(!open)}>
        <div>
          <h2 className="text-base font-semibold text-slate-900">高级设置：追加 System Prompt</h2>
          {/* <p className="mt-1 text-sm text-slate-500">这里填写的内容不会覆盖默认 prompts/*.md，只会在本次请求中追加到默认 system prompt 后面。</p> */}
        </div>
        <ChevronDown className={`h-5 w-5 text-slate-500 transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open ? (
        <div className="mt-5 space-y-4">
          <div className="flex flex-wrap gap-2">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActive(tab.key)}
                className={`rounded-xl px-3 py-2 text-sm transition ${active === tab.key ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <textarea
            className="input min-h-[150px] resize-y"
            value={value[active]}
            onChange={(event) => update(active, event.target.value)}
            placeholder="可选：输入本次请求需要追加的 system prompt 内容"
          />
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><FileText className="h-4 w-4" />默认 prompt 只读预览</div>
              <button type="button" className="btn-secondary" onClick={loadDefaults} disabled={loadingPreview}>
                {loadingPreview ? "读取中..." : "读取默认 prompt"}
              </button>
            </div>
            {previewError ? <p className="text-sm text-red-600">{previewError}</p> : null}
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-600">
              {defaultPrompts ? defaultPrompts[active] || "当前项没有默认 prompt 文件。" : "点击按钮后可以查看默认 prompt，编辑区只保存追加内容。"}
            </pre>
          </div>
        </div>
      ) : null}
    </section>
  );
}
