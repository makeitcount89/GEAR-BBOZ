import { NextResponse } from "next/server";
import type { WorkflowStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

const OWNER = process.env.GITHUB_REPO_OWNER ?? "makeitcount89";
const REPO = process.env.GITHUB_REPO_NAME ?? "GEAR-BBOZ";
const WORKFLOW_FILE = process.env.GITHUB_WORKFLOW_FILE ?? "run_strategy.yml";

/**
 * Serverless proxy for the GitHub Actions REST API. Runs entirely on the server so
 * the browser never talks to api.github.com directly -- this sidesteps CORS and
 * keeps an optional GITHUB_TOKEN (for higher rate limits) out of client code.
 */
export async function GET() {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=1`;

  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  const token = process.env.GITHUB_TOKEN ?? process.env.GH_TOKEN;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  try {
    const res = await fetch(url, { headers, cache: "no-store" });

    if (!res.ok) {
      const body: WorkflowStatus = {
        status: null,
        conclusion: null,
        name: null,
        runStartedAt: null,
        updatedAt: null,
        htmlUrl: null,
        event: null,
        runNumber: null,
        error: `GitHub API responded ${res.status} ${res.statusText}`,
      };
      return NextResponse.json(body, { status: 200 });
    }

    const data = await res.json();
    const run = data.workflow_runs?.[0];

    if (!run) {
      const body: WorkflowStatus = {
        status: null,
        conclusion: null,
        name: null,
        runStartedAt: null,
        updatedAt: null,
        htmlUrl: null,
        event: null,
        runNumber: null,
        error: "No workflow runs found yet",
      };
      return NextResponse.json(body, { status: 200 });
    }

    const body: WorkflowStatus = {
      status: run.status,
      conclusion: run.conclusion,
      name: run.name,
      runStartedAt: run.run_started_at,
      updatedAt: run.updated_at,
      htmlUrl: run.html_url,
      event: run.event,
      runNumber: run.run_number,
    };

    return NextResponse.json(body, { status: 200 });
  } catch (err) {
    const body: WorkflowStatus = {
      status: null,
      conclusion: null,
      name: null,
      runStartedAt: null,
      updatedAt: null,
      htmlUrl: null,
      event: null,
      runNumber: null,
      error: err instanceof Error ? err.message : "Unknown error contacting GitHub API",
    };
    return NextResponse.json(body, { status: 200 });
  }
}
