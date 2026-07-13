import { cn } from "@/lib/utils";

export default function StatTile({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  tone?: "good" | "bad" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-4">
      <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
        {icon}
        {label}
      </div>
      <div
        className={cn(
          "mt-2 text-2xl font-semibold tabular",
          tone === "good" && "text-[var(--status-good)]",
          tone === "bad" && "text-[var(--status-critical)]"
        )}
      >
        {value}
      </div>
    </div>
  );
}
