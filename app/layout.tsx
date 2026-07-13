import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GEAR/BBOZ Bi-Weekly ML Allocator",
  description:
    "Rolling k-NN trend-following allocation dashboard for GEAR.AX / BBOZ.AX on the ASX",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[var(--page-plane)] font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
