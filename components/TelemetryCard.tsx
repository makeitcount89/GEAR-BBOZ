"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, CheckCircle2, ExternalLink, HelpCircle, Loader2, XCircle } from "lucide-react";
import type { WorkflowStatus } from "@/lib/types";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";

const POLL_MS = 60_000;

function statusPresentation(w: WorkflowStatus | null) {
  if (!w || w.error) {
    return { label: "Unknown", icon: HelpCircle, color: "text-[var(--text-muted)]" };
  }
  if (w.status === "in_progress" || w.status === "queued") {
    return { label: w.status === "queued" ? "Queued" : "Running", icon: Loader2, color: "text-[var(--status-warning)]", spin: true };
  }
  if (w.conclusion === "success") {
    return { label: "Success", icon: CheckCircle2, color: "text-[var(--status-good)]" };
  }
  if (w.conclusion) {
    return { label: w.conclusion, icon: XCircle, color: "text-[var(--status-critical)]" };
  }
  return { label: w.status ?? "Unknown", icon: HelpCircle, color: "text-[var(--text-muted)]" };
}

export default function TelemetryCard() {
  const [data, setData] = useState<WorkflowStatus | null>(null);
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/workflow-status", { cache: "no-store" });
      const json: WorkflowStatus = await res.json();
      setData(json);
      setFetchedAt(Date.now());
    } catch {
      setData({
        status: null,
        conclusion: null,
        name: null,
        runStartedAt: null,
        updatedAt: null,
        htmlUrl: null,
        event: null,
        runNumber: null,
        error: "Failed to reach status endpoint",
      });
      setFetchedAt(Date.now());
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const presentation = statusPresentation(data);
  const Icon = presentation.icon;

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
          <Activity size={16} className="text-[var(--series-profit)]" />
          System Telemetry — Cron Pipeline
        </h2>
        {fetchedAt && <span className="text-xs text-[var(--text-muted)]">checked {timeAgo(new Date(fetchedAt).toISOString())}</span>}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Icon size={28} className={cn(presentation.color, presentation.spin && "animate-spin")} />
        <div>
          <div className={cn("text-lg font-semibold", presentation.color)}>{presentation.label}</div>
          {data?.error && <div className="text-xs text-[var(--text-muted)]">{data.error}</div>}
        </div>
      </div>

      {data && !data.error && (
        <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-base-700 pt-4 text-sm">
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Run #</dt>
            <dd className="tabular font-medium">{data.runNumber ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Trigger</dt>
            <dd className="font-medium">{data.event ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Started</dt>
            <dd className="font-medium">{formatDateTime(data.runStartedAt)}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--text-muted)]">Updated</dt>
            <dd className="font-medium">{formatDateTime(data.updatedAt)}</dd>
          </div>
        </dl>
      )}

      {data?.htmlUrl && (
        <a
          href={data.htmlUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 flex items-center gap-1.5 text-xs font-medium text-[var(--series-profit)] hover:underline"
        >
          View run logs on GitHub <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}
