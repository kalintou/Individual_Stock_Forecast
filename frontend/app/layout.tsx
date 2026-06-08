import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "个股智能分析系统",
  description: "基于技术面、基本面、资金面、情绪面的 A 股多因子智能分析",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
