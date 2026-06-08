"use client";

import { useState } from "react";
import { ChevronDown, GitBranch } from "lucide-react";
import type { TraceEntry } from "@/lib/types";

interface TraceBarProps {
  trace: TraceEntry[];
  loading?: boolean;
}

type TraceRow = TraceEntry & {
  node_label: string;
  status: string;
  output_summary: string;
};

const loadingSteps = ["解析用户意图", "市场结构定位", "因子路由", "四因子分析", "综合融合", "生成最终报告"];

const nodeOrder = [
  "intent_clarification_node",
  "market_structure_node",
  "sector_router_node",
  "technical_analysis_node",
  "fundamental_analysis_node",
  "capital_analysis_node",
  "sentiment_analysis_node",
  "cross_sector_fusion_node",
  "final_answer_node",
  "failure_node",
];

function normalizeTraceRows(trace: TraceEntry[] = [], loading?: boolean): TraceRow[] {
  if (trace.length > 0) {
    const latestByNode = new Map<string, TraceRow>();
    const unknownRows: TraceRow[] = [];

    for (const item of trace) {
      const node = item.node || item.node_label || "unknown";
      const row: TraceRow = {
        ...item,
        node,
        node_label: item.node_label || item.node || "未知节点",
        status: item.status || "完成",
        output_summary: item.output_summary || "暂无摘要",
      };

      if (nodeOrder.includes(node)) {
        latestByNode.set(node, row);
      } else {
        unknownRows.push(row);
      }
    }

    return [
      ...nodeOrder.flatMap((node) => {
        const row = latestByNode.get(node);
        return row ? [row] : [];
      }),
      ...unknownRows,
    ];
  }

  if (loading) {
    return loadingSteps.map((step) => ({
      node: step,
      node_label: step,
      status: "执行中",
      output_summary: "等待节点返回结果",
    }));
  }

  return [];
}

export function TraceBar({ trace, loading }: TraceBarProps) {
  const [open, setOpen] = useState(false);
  const rows = normalizeTraceRows(trace, loading);
  if (!loading && rows.length === 0) return null;

  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className={`flex-1 overflow-hidden transition-all ${open ? "max-h-[520px]" : "max-h-[2.6rem]"}`}>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <GitBranch className="h-4 w-4" />执行轨迹 / Trace
          </div>
          <div className="space-y-2">
            {rows.map((item, index) => (
              <div key={`${item.node}-${index}`} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                <span className="font-medium text-slate-900">{index + 1}. {item.node_label}</span>
                <span className="ml-2 text-xs text-slate-400">{item.elapsed_ms ? `${item.elapsed_ms}ms` : ""}</span>
                <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-xs text-slate-500">{item.status}</span>
                <span className="ml-2">{item.output_summary}</span>
              </div>
            ))}
          </div>
        </div>
        <button type="button" className="btn-secondary shrink-0" onClick={() => setOpen(!open)}>
          {open ? "收起" : "展开"}
          <ChevronDown className={`ml-1 h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
        </button>
      </div>
    </section>
  );
}
