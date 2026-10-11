import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DetailDrawer } from "../components/DetailDrawer";
import { setConfig } from "../lib/api";

describe("Runtime evidence inspector", () => {
  beforeEach(() => setConfig({ url: "http://localhost:8770", token: "fake.service" }));
  afterEach(() => vi.unstubAllGlobals());

  it("loads actual CAS metadata and shows a digest mismatch without an effect claim", async () => {
    const digest = "sha256:" + "a".repeat(64);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {
      artifact_id: digest, artifact: { name: "original-result", digest },
      integrity: "MISMATCH", effect_verification_performed: false,
      scope: "runtime-service-artifact-cas",
    } })));
    vi.stubGlobal("fetch", fetcher);
    render(<DetailDrawer view={{ kind: "artifact", artifactId: digest }} onClose={vi.fn()} />);
    expect(await screen.findByText("MISMATCH")).toBeInTheDocument();
    expect(screen.getByText(/original-result/)).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.get("artifact_id")).toBe(digest);
  });

  it("reports unavailable evidence as an error, without retaining the previous artifact", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, data: { name: "previous-artifact" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: false, error: { code: "NOT_AVAILABLE", message: "Artifact registry is unavailable" } }), { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = render(<DetailDrawer view={{ kind: "artifact", artifactId: "artifact_old" }} onClose={vi.fn()} />);
    await screen.findByText("previous-artifact");
    rerender(<DetailDrawer view={{ kind: "artifact", artifactId: "artifact_new" }} onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Artifact registry is unavailable");
    expect(screen.queryByText("previous-artifact")).not.toBeInTheDocument();
  });

  it("keeps UNKNOWN unverified despite a passing evaluation", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {
      task_id: "task_original", verdict: "UNKNOWN", verified: false, committed: false,
      evaluation: { score: 1, passed: true }, effect_verification: {},
      scope: "recorded-runtime-service-effect-verification",
    } })));
    vi.stubGlobal("fetch", fetcher);
    render(<DetailDrawer view={{ kind: "verification", taskId: "task_original" }} onClose={vi.fn()} />);
    expect(await screen.findByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getAllByText("false")).toHaveLength(2);
    expect(fetcher.mock.calls[0][0]).toContain("/tasks/task_original/verification");
  });

  it("loads persisted task activity and verification through the task inspector", async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => {
      const path = new URL(url).pathname;
      const data = path.endsWith("verification") ? { verdict: "MISMATCH", verified: false }
        : path.endsWith("timeline") ? { events: [{ event_id: "event_original", data: { work_id: "work_original" } }] }
        : { tasks: [{ task_id: "work_original", name: "Original Work", status: "blocked" }] };
      return new Response(JSON.stringify({ ok: true, data }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<DetailDrawer view={{ kind: "task", taskId: "work_original" }} onClose={vi.fn()} />);
    expect(await screen.findByText("Original Work")).toBeInTheDocument();
    expect(await screen.findByText("MISMATCH")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/event_original/)).toBeInTheDocument());
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("reads a searched Run from EventStream, rather than treating it as a tracer ID", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {
      task_id: "run_original", events: [{ event_id: "event_persisted", data: { outcome: "UNKNOWN" } }],
    } })));
    vi.stubGlobal("fetch", fetcher);
    render(<DetailDrawer view={{ kind: "run", runId: "run_original" }} onClose={vi.fn()} />);
    expect(await screen.findByText(/event_persisted/)).toBeInTheDocument();
    expect(new URL(fetcher.mock.calls[0][0]).pathname).toBe("/api/v1/tasks/timeline");
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.get("task_id")).toBe("run_original");
  });
});
