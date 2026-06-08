import type { AnalyzeRequest, AnalyzeResponse, ChartDataResponse, HotStock, TraceEntry } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function parseJsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败：${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function analyzeStock(payload: AnalyzeRequest): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonOrThrow<AnalyzeResponse>(res);
}

interface AnalyzeStreamCallbacks {
  onTrace?: (trace: TraceEntry[]) => void;
  onStatus?: (message: string) => void;
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  const lines = block.split("\n").map((line) => line.trimEnd());
  let event = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export async function analyzeStockStream(
  payload: AnalyzeRequest,
  callbacks: AnalyzeStreamCallbacks = {},
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/api/analyze/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败：${res.status}`);
  }

  if (!res.body) {
    return analyzeStock(payload);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: AnalyzeResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
      const parsed = parseSseBlock(block);
      if (!parsed) continue;

      const data = parsed.data as Record<string, unknown>;
      if (parsed.event === "started") {
        callbacks.onStatus?.(String(data.message || "分析任务已开始"));
      } else if (parsed.event === "trace") {
        const trace = Array.isArray(data.trace) ? (data.trace as TraceEntry[]) : [];
        callbacks.onTrace?.(trace);
      } else if (parsed.event === "final") {
        finalResponse = data as unknown as AnalyzeResponse;
        callbacks.onTrace?.(finalResponse.trace || []);
      } else if (parsed.event === "error") {
        throw new Error(String(data.error_message || "分析请求失败"));
      }
    }
  }

  if (!finalResponse) {
    throw new Error("分析流结束，但没有收到最终结果。请检查后端日志。 ");
  }
  return finalResponse;
}

export async function fetchHotStocks(topN = 30): Promise<HotStock[]> {
  const res = await fetch(`${API_BASE}/api/hot-stocks?top_n=${topN}`, { cache: "no-store" });
  return parseJsonOrThrow<HotStock[]>(res);
}

export async function fetchChartData(stockCode: string): Promise<ChartDataResponse> {
  const res = await fetch(`${API_BASE}/api/chart-data/${encodeURIComponent(stockCode)}`, { cache: "no-store" });
  return parseJsonOrThrow<ChartDataResponse>(res);
}

export async function fetchPrompts(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/api/prompts`, { cache: "no-store" });
  return parseJsonOrThrow<Record<string, string>>(res);
}
