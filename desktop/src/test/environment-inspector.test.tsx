import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EnvironmentInspector } from "../components/EnvironmentInspector";
import {
  ApiError,
  approvalAction,
  createEnvironment,
  destroyEnvironment,
  fetchEnvironmentLogs,
  fetchEnvironments,
  fetchEnvironmentStatus,
  runEnvironment,
  startEnvironment,
  stopEnvironment,
  type EnvironmentRecord,
} from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    approvalAction: vi.fn(),
    createEnvironment: vi.fn(),
    destroyEnvironment: vi.fn(),
    fetchEnvironmentLogs: vi.fn(),
    fetchEnvironments: vi.fn(),
    fetchEnvironmentStatus: vi.fn(),
    runEnvironment: vi.fn(),
    startEnvironment: vi.fn(),
    stopEnvironment: vi.fn(),
  };
});

const readyEnvironment: EnvironmentRecord = {
  schema_version: "nous.environment/v1",
  environment_id: "env_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  environment_type: "local_sandbox",
  provider: "local-sandbox",
  image: "",
  architecture: "amd64",
  os: "windows",
  cpu_limit: 1,
  memory_limit_mb: 512,
  gpu_policy: "none",
  network_policy: { mode: "none", allowed_hosts: [] },
  filesystem_policy: { read_only_root: true, temporary_filesystem_mb: 64 },
  device_policy: { gpu: "none", devices: [] },
  workspace_mounts: [],
  lifetime_seconds: 3600,
  state: "ready",
  provider_handle: "C:/workspace/.nous/environment",
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
  last_error: "",
  sha256: "a".repeat(64),
};

describe("environment inspector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchEnvironmentStatus).mockResolvedValue({
      schema_version: "nous.environment-runtime/v1",
      workspace: "C:/workspace",
      environments: 0,
      providers: [
        {
          provider_id: "local-sandbox",
          contract_version: "nous.environment-provider/v1",
          available: true,
          environment_type: "local_sandbox",
          evidence_level: "integrated-host",
          hard_network_isolation: false,
          filesystem_namespace_isolation: false,
        },
        {
          provider_id: "oci",
          contract_version: "nous.environment-provider/v1",
          available: false,
          environment_type: "oci_container",
          evidence_level: "static",
          limitations: ["No engine"],
        },
      ],
      compatibility: {},
      defaults: { network: "none", privileged: false },
      event_authority: "EventStream",
      artifact_authority: "ArtifactRegistry",
      state_authority: ".nous/environments/records",
    });
    vi.mocked(fetchEnvironments).mockResolvedValue({ environments: [], total: 0 });
    vi.mocked(fetchEnvironmentLogs).mockResolvedValue({
      environment_id: readyEnvironment.environment_id,
      provider: "local-sandbox",
      state: "ready",
      text: "log",
    });
    vi.mocked(approvalAction).mockResolvedValue({});
  });

  it("shows truthful host isolation and retries identical create after approval", async () => {
    vi.mocked(createEnvironment)
      .mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_environment" }))
      .mockResolvedValueOnce({ ...readyEnvironment, state: "created", artifact_id: "artifact_environment" });

    render(<EnvironmentInspector />);
    expect(await screen.findByText(/integrated-host only/)).toBeInTheDocument();
    expect(screen.getByText(/OCI not installed/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create governed environment" }));
    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and create" }));

    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_environment", "approve"));
    await waitFor(() => expect(createEnvironment).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createEnvironment).mock.calls[1][0]).toBe(vi.mocked(createEnvironment).mock.calls[0][0]);
  });

  it("runs argv without a shell and exposes Artifact evidence", async () => {
    vi.mocked(fetchEnvironments).mockResolvedValue({ environments: [readyEnvironment], total: 1 });
    vi.mocked(runEnvironment).mockResolvedValue({
      environment_id: readyEnvironment.environment_id,
      state: "ready",
      operation_run_id: "environment-run-ui",
      artifact_id: "artifact_environment_run",
      artifact: {
        location: "artifacts/environments/run.json",
        sha256: "b".repeat(64),
        size_bytes: 1024,
      },
      ok: true,
      exit_code: 0,
      stdout: "Python 3.14",
      stderr: "",
      wall_time_seconds: 0.1,
      peak_memory_bytes: 1024,
      timed_out: false,
      output_truncated: false,
    });

    render(<EnvironmentInspector />);
    await screen.findByRole("option", { name: /local_sandbox - ready/ });
    fireEvent.click(screen.getByRole("button", { name: "Run in environment" }));

    expect(await screen.findByText(/artifact_environment_run/)).toBeInTheDocument();
    expect(screen.getByText("Python 3.14")).toBeInTheDocument();
    expect(runEnvironment).toHaveBeenCalledWith(
      readyEnvironment.environment_id,
      expect.objectContaining({ argv: ["python", "-V"] }),
    );
  });
});
