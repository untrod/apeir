import React, { useCallback, useEffect, useMemo, useState } from "react";

import { btnPrimary, btnSecondary, card, colors, input, radius, space, typo } from "../design";
import {
  ApiError,
  approvalAction,
  analyzeSimulationRun,
  cancelSimulation,
  createSimulation,
  fetchScientificAnalyses,
  fetchScientificStatus,
  fetchSimulationRuns,
  fetchSimulations,
  fetchSimulationStatus,
  replaySimulation,
  runSimulation,
  type ScientificAnalysisRecord,
  type ScientificRuntimeStatus,
  type SimulationCreateRequest,
  type SimulationRecord,
  type SimulationRunRecord,
  type SimulationRuntimeStatus,
} from "../lib/api";
import { errorMessage, fixedNumber } from "../lib/format";

type Pending =
  | { kind: "create"; approvalId: string; request: SimulationCreateRequest }
  | { kind: "run"; approvalId: string; simulationId: string }
  | { kind: "cancel"; approvalId: string; simulationId: string }
  | { kind: "replay"; approvalId: string; runId: string }
  | { kind: "analyze"; approvalId: string; runId: string };

const defaultMetrics = [
  "peak_temperature",
  "equilibrium_temperature",
  "final_temperature",
  "safety_margin",
  "sample_count",
];

export function SimulationWorkbench() {
  const [status, setStatus] = useState<SimulationRuntimeStatus | null>(null);
  const [scientificStatus, setScientificStatus] = useState<ScientificRuntimeStatus | null>(null);
  const [analyses, setAnalyses] = useState<ScientificAnalysisRecord[]>([]);
  const [simulations, setSimulations] = useState<SimulationRecord[]>([]);
  const [runs, setRuns] = useState<SimulationRunRecord[]>([]);
  const [selected, setSelected] = useState("");
  const [selectedRun, setSelectedRun] = useState("");
  const [initialTemperature, setInitialTemperature] = useState(290);
  const [externalTemperature, setExternalTemperature] = useState(3);
  const [solarFlux, setSolarFlux] = useState(1361);
  const [surfaceArea, setSurfaceArea] = useState(2);
  const [emissivity, setEmissivity] = useState(0.8);
  const [thermalCapacity, setThermalCapacity] = useState(10000);
  const [timeStep, setTimeStep] = useState(1);
  const [duration, setDuration] = useState(600);
  const [seed, setSeed] = useState(42);
  const [maxCases, setMaxCases] = useState(16);
  const [maxRetries, setMaxRetries] = useState(0);
  const [sweepText, setSweepText] = useState('{"solar_flux":[900,1100,1361]}');
  const [pending, setPending] = useState<Pending | null>(null);
  const [runningSimulation, setRunningSimulation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [nextStatus, nextSimulations, nextRuns, nextScientificStatus, nextAnalyses] = await Promise.all([
      fetchSimulationStatus(),
      fetchSimulations(),
      fetchSimulationRuns(selected),
      fetchScientificStatus(),
      fetchScientificAnalyses(),
    ]);
    setStatus(nextStatus);
    setScientificStatus(nextScientificStatus);
    setAnalyses(nextAnalyses.analyses);
    setSimulations(nextSimulations.simulations);
    setRuns(nextRuns.runs);
    if (!selected && nextSimulations.simulations[0]?.simulation_id) {
      setSelected(nextSimulations.simulations[0].simulation_id);
    }
    if (!selectedRun && nextRuns.runs[0]?.simulation_run_id) {
      setSelectedRun(nextRuns.runs[0].simulation_run_id);
    }
  }, [selected, selectedRun]);

  useEffect(() => {
    void refresh().catch((cause) =>
      setError(errorMessage(cause, "Simulation Runtime is unavailable.")),
    );
  }, [refresh]);

  const current = useMemo(
    () => simulations.find((item) => item.simulation_id === selected) || null,
    [simulations, selected],
  );
  const currentRun = useMemo(
    () => runs.find((item) => item.simulation_run_id === selectedRun) || runs[0] || null,
    [runs, selectedRun],
  );
  const currentAnalysis = useMemo(
    () => analyses.find((item) => item.simulation_run_id === currentRun?.simulation_run_id) || null,
    [analyses, currentRun],
  );

  const requestFromForm = (): SimulationCreateRequest => {
    let parameterSpace: unknown;
    try {
      parameterSpace = JSON.parse(sweepText || "{}");
    } catch {
      throw new Error("Parameter sweep must be a valid JSON object.");
    }
    if (!parameterSpace || Array.isArray(parameterSpace) || typeof parameterSpace !== "object") {
      throw new Error("Parameter sweep must be a JSON object.");
    }
    return {
      model_ref: "spacecraft-thermal/v1",
      environment_type: "local_sandbox",
      provider: "local-sandbox",
      initial_state: { initial_temperature: initialTemperature },
      boundary_conditions: { external_temperature: externalTemperature },
      parameters: {
        solar_flux: solarFlux,
        surface_area: surfaceArea,
        emissivity,
        thermal_capacity: thermalCapacity,
        absorptivity: 0.7,
        max_safe_temperature: 373.15,
      },
      solver: "explicit-euler",
      time_step: timeStep,
      duration,
      seed,
      resource_budget: {
        cpu_limit: 1,
        memory_limit_mb: 512,
        wall_time_seconds: 300,
        max_cases: maxCases,
        max_retries: maxRetries,
        max_output_bytes: 20_000_000,
      },
      network_policy: { mode: "none" },
      metric_schema: defaultMetrics,
      output_schema: ["json", "csv", "svg"],
      parameter_space: parameterSpace as Record<string, number[]>,
      numerical_tolerance: { absolute: 1e-9, relative: 1e-9 },
    };
  };

  const captureApproval = (cause: unknown, value: Pending): boolean => {
    if (!(cause instanceof ApiError) || cause.code !== "NOUS_APPROVAL_REQUIRED") return false;
    const approvalId = String(cause.details?.approval_request_id || "");
    if (!approvalId) return false;
    setPending({ ...value, approvalId } as Pending);
    return true;
  };

  const executeCreate = async (request: SimulationCreateRequest) => {
    setBusy(true);
    setError("");
    try {
      const result = await createSimulation(request);
      setSelected(result.simulation_id);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "create", approvalId: "", request })) {
        setError(errorMessage(cause, "Simulation creation failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeRun = async (simulationId: string) => {
    setBusy(true);
    setRunningSimulation(simulationId);
    setError("");
    try {
      const result = await runSimulation(simulationId);
      setSelectedRun(result.simulation_run_id);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "run", approvalId: "", simulationId })) {
        setError(errorMessage(cause, "Simulation execution failed."));
      }
    } finally {
      setRunningSimulation("");
      setBusy(false);
    }
  };

  const executeReplay = async (runId: string) => {
    setBusy(true);
    setError("");
    try {
      const result = await replaySimulation(runId);
      setSelectedRun(result.simulation_run_id);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "replay", approvalId: "", runId })) {
        setError(errorMessage(cause, "Simulation replay failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeAnalyze = async (runId: string) => {
    setBusy(true);
    setError("");
    try {
      await analyzeSimulationRun(runId);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "analyze", approvalId: "", runId })) {
        setError(errorMessage(cause, "Scientific analysis and report generation failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeCancel = async (simulationId: string) => {
    setError("");
    try {
      await cancelSimulation(simulationId);
      setPending(null);
    } catch (cause) {
      if (!captureApproval(cause, { kind: "cancel", approvalId: "", simulationId })) {
        setError(errorMessage(cause, "Simulation cancellation failed."));
      }
    }
  };

  const approveAndContinue = async () => {
    if (!pending) return;
    const reviewed = pending;
    setBusy(true);
    setError("");
    try {
      await approvalAction(reviewed.approvalId, "approve");
      setBusy(false);
      if (reviewed.kind === "create") await executeCreate(reviewed.request);
      else if (reviewed.kind === "run") await executeRun(reviewed.simulationId);
      else if (reviewed.kind === "replay") await executeReplay(reviewed.runId);
      else if (reviewed.kind === "analyze") await executeAnalyze(reviewed.runId);
      else await executeCancel(reviewed.simulationId);
    } catch (cause) {
      setError(errorMessage(cause, "Approval could not be applied."));
      setBusy(false);
    }
  };

  const requestCreate = () => {
    try {
      void executeCreate(requestFromForm());
    } catch (cause) {
      setError(errorMessage(cause, "Simulation contract is invalid."));
    }
  };

  return (
    <div style={{ height: "100%", overflowY: "auto", background: colors.bg, padding: space.xl }}>
      <div style={{ maxWidth: 1220, margin: "0 auto", display: "grid", gap: space.lg }}>
        <section style={{ ...card, display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text }}>Simulations</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: space.xs }}>
              Simulation Contract - EnvironmentRuntime - deterministic replay - Artifact evidence
            </div>
          </div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm }}>
            {status
              ? `${status.simulations} contracts - ${status.completed} completed - ${status.active} active`
              : "Checking scientific providers..."}
            {scientificStatus && (
              <span> - {Object.values(scientificStatus.providers).filter((item) => item.available).length}/5 providers</span>
            )}
          </div>
        </section>

        <section style={{ ...card, borderColor: colors.warning, background: colors.warningSoft, color: colors.textSecondary, fontSize: typo.sm }}>
          Local scientific execution is integrated-host on Windows 10. Network is OFF, limits and process cleanup are enforced, but hard filesystem/network namespaces require an OCI engine.
        </section>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(330px, .9fr) minmax(0, 1.5fr)", gap: space.lg }}>
          <section style={card}>
            <div style={sectionTitle}>Spacecraft thermal analysis</div>
            <div style={twoColumns}>
              <Field label="Initial K" value={initialTemperature} setValue={setInitialTemperature} />
              <Field label="External K" value={externalTemperature} setValue={setExternalTemperature} />
              <Field label="Solar flux W/m2" value={solarFlux} setValue={setSolarFlux} />
              <Field label="Area m2" value={surfaceArea} setValue={setSurfaceArea} />
              <Field label="Emissivity" value={emissivity} setValue={setEmissivity} step={0.01} />
              <Field label="Thermal capacity" value={thermalCapacity} setValue={setThermalCapacity} />
              <Field label="Time step s" value={timeStep} setValue={setTimeStep} step={0.1} />
              <Field label="Duration s" value={duration} setValue={setDuration} />
              <Field label="Seed" value={seed} setValue={setSeed} />
              <Field label="Max cases" value={maxCases} setValue={setMaxCases} />
              <Field label="Max retries" value={maxRetries} setValue={setMaxRetries} />
            </div>
            <label style={labelStyle}>Parameter sweep JSON</label>
            <textarea aria-label="Parameter sweep JSON" value={sweepText} onChange={(event) => setSweepText(event.target.value)} rows={3} style={{ ...input, resize: "vertical", fontFamily: "monospace" }} />
            <div style={policyStyle}>Solver: explicit Euler - Network: OFF - GPU: NONE - Outputs: JSON + CSV + SVG</div>
            <button onClick={requestCreate} disabled={busy} style={{ ...btnPrimary, marginTop: space.md, opacity: busy ? 0.55 : 1 }}>
              Create reproducible simulation
            </button>
          </section>

          <section style={card}>
            <div style={sectionTitle}>Run and inspect</div>
            <select aria-label="Simulation library" value={selected} onChange={(event) => { setSelected(event.target.value); setSelectedRun(""); }} style={{ ...input, marginTop: space.md }}>
              <option value="">Select a simulation</option>
              {simulations.map((item) => (
                <option key={item.simulation_id} value={item.simulation_id}>
                  {item.simulation_id.slice(-12)} - {item.model_ref} - {item.state}
                </option>
              ))}
            </select>
            {current && (
              <>
                <div style={{ ...detailGrid, marginTop: space.md }}>
                  <Detail label="Model" value={current.model_ref} />
                  <Detail label="Cases" value={String(Object.values(current.parameter_space).reduce((n, values) => n * values.length, 1))} />
                  <Detail label="Seed" value={String(current.seed)} />
                  <Detail label="Spec SHA-256" value={current.sha256.slice(0, 16)} />
                </div>
                <div style={{ display: "flex", gap: space.sm, marginTop: space.md, flexWrap: "wrap" }}>
                  <button onClick={() => void executeRun(current.simulation_id)} disabled={busy} style={btnPrimary}>Run in environment</button>
                  {runningSimulation === current.simulation_id && (
                    <button onClick={() => void executeCancel(current.simulation_id)} style={{ ...btnSecondary, color: colors.danger }}>Cancel active run</button>
                  )}
                </div>
              </>
            )}
            <select aria-label="Simulation runs" value={selectedRun} onChange={(event) => setSelectedRun(event.target.value)} style={{ ...input, marginTop: space.md }}>
              <option value="">Select a run</option>
              {runs.map((item) => (
                <option key={item.simulation_run_id} value={item.simulation_run_id}>
                  {item.simulation_run_id.slice(-12)} - {item.state} - {item.case_count || 0} cases
                </option>
              ))}
            </select>
            {currentRun && (
              <RunEvidence
                run={currentRun}
                analysis={currentAnalysis}
                replay={() => void executeReplay(currentRun.simulation_run_id)}
                analyze={() => void executeAnalyze(currentRun.simulation_run_id)}
                busy={busy}
              />
            )}
          </section>
        </div>

        {pending && (
          <section style={{ ...card, borderColor: colors.warning, background: colors.warningSoft }}>
            <div style={sectionTitle}>Explicit approval required</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.sm, margin: `${space.sm} 0` }}>
              Review this scoped scientific-compute effect. Approval is single-use and the identical request is retried.
            </div>
            <button onClick={() => void approveAndContinue()} style={btnPrimary}>Approve once and {pending.kind}</button>
          </section>
        )}
        {error && <section style={{ ...card, color: colors.danger, borderColor: colors.danger }}>{error}</section>}
      </div>
    </div>
  );
}

function RunEvidence({
  run,
  analysis,
  replay,
  analyze,
  busy,
}: {
  run: SimulationRunRecord;
  analysis: ScientificAnalysisRecord | null;
  replay: () => void;
  analyze: () => void;
  busy: boolean;
}) {
  return (
    <div style={{ marginTop: space.md, display: "grid", gap: space.md }}>
      <div style={detailGrid}>
        <Detail label="State" value={run.state} />
        <Detail label="Cases" value={String(run.case_count || 0)} />
        <Detail label="Attempts" value={String(run.execution_attempts?.length || 0)} />
        <Detail label="Result digest" value={(run.result_digest || "").slice(0, 16) || "-"} />
      </div>
      {run.replay && (
        <div style={{ color: run.replay.verified ? colors.success : colors.danger, fontSize: typo.sm }}>
          Replay {run.replay.verified ? "verified" : "mismatch"} - max error {run.replay.maximum_absolute_error}
        </div>
      )}
      {run.cases?.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", color: colors.text, fontSize: typo.xs }}>
            <thead><tr><th style={cell}>Case</th><th style={cell}>Peak K</th><th style={cell}>Final K</th><th style={cell}>Safety margin</th></tr></thead>
            <tbody>{run.cases.map((item) => <tr key={item.case_id}><td style={cell}>{item.case_id}</td><td style={cell}>{fixedNumber(item.metrics.peak_temperature, 3)}</td><td style={cell}>{fixedNumber(item.metrics.final_temperature, 3)}</td><td style={cell}>{fixedNumber(item.metrics.safety_margin, 3)}</td></tr>)}</tbody>
          </table>
        </div>
      )}
      {run.artifacts?.length > 0 && (
        <div>{run.artifacts.map((artifact) => <div key={artifact.artifact_id} style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: 3 }}>{artifact.name} - {artifact.location} - {artifact.sha256.slice(0, 12)}</div>)}</div>
      )}
      {run.state === "completed" && (
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <button onClick={replay} disabled={busy} style={btnSecondary}>Replay and verify tolerance</button>
          <button onClick={analyze} disabled={busy} style={btnPrimary}>Analyze and generate DOCX/PDF</button>
        </div>
      )}
      {analysis && (
        <section style={{ ...detailGrid, gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
          <Detail label="Scientific result" value={analysis.reference_verified ? "Reference verified" : analysis.state} />
          <Detail label="Max reference error K" value={fixedNumber(analysis.maximum_reference_error_kelvin, 9)} />
          <Detail label="Claims" value={String(analysis.claim_ids.length)} />
          <Detail label="Environment" value={analysis.environment_state} />
          <Detail label="Technical report" value={analysis.document?.verified ? "DOCX + PDF verified" : "-"} />
          <Detail label="Analysis ID" value={analysis.analysis_id.slice(-12)} />
        </section>
      )}
      {run.reproducibility && <details><summary style={{ color: colors.textSecondary, cursor: "pointer", fontSize: typo.sm }}>Reproducibility manifest</summary><pre style={preStyle}>{JSON.stringify(run.reproducibility, null, 2)}</pre></details>}
      {run.error && <div style={{ color: colors.danger, fontSize: typo.sm }}>{run.error}</div>}
    </div>
  );
}

function Field({ label, value, setValue, step = 1 }: { label: string; value: number; setValue: (value: number) => void; step?: number }) {
  return <div><label style={labelStyle}>{label}</label><input aria-label={label} type="number" value={value} step={step} onChange={(event) => setValue(Number(event.target.value))} style={input} /></div>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><div style={{ color: colors.textTertiary, fontSize: typo.xs }}>{label}</div><div style={{ color: colors.text, fontSize: typo.sm, marginTop: 2, wordBreak: "break-word" }}>{value}</div></div>;
}

const sectionTitle: React.CSSProperties = { color: colors.text, fontWeight: typo.semibold };
const labelStyle: React.CSSProperties = { display: "block", color: colors.textSecondary, fontSize: typo.xs, marginTop: space.md, marginBottom: space.xs };
const policyStyle: React.CSSProperties = { color: colors.textTertiary, fontSize: typo.xs, lineHeight: 1.6, marginTop: space.md };
const twoColumns: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: space.sm };
const detailGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: space.md, padding: space.md, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md };
const cell: React.CSSProperties = { borderBottom: `1px solid ${colors.borderLight}`, padding: space.sm, textAlign: "left" };
const preStyle: React.CSSProperties = { whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 260, overflow: "auto", background: colors.bg, color: colors.text, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md, padding: space.md, fontSize: typo.xs };
