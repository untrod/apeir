import React, { useCallback, useEffect, useId, useRef, useState } from "react";

import { btnPrimary, btnSecondary, colors, radius, space, typo } from "../design";
import {
  createDeveloperExperiment,
  createDeveloperProject,
  developerProjectAction,
  evaluateDeveloperExperiment,
  fetchDeveloperExperiments,
  fetchDeveloperOverview,
  fetchDeveloperProjects,
  fetchDeveloperRuns,
  fetchModelLab,
  getConfig,
  getRuntimeConfigVersion,
  type DeveloperExperiment,
  type DeveloperOverview,
  type DeveloperProject,
  type DeveloperRun,
  type ExperimentResultView,
  type ModelLabSnapshot,
} from "../lib/api";
import { errorMessage, fixedNumber } from "../lib/format";
import { DeveloperWorkbench } from "./DeveloperWorkbench";
import { ResearchEvidence } from "./ResearchEvidence";
import { UsageAccounting } from "./UsageAccounting";
import { isUsageAccountingSummary, usageNumber } from "../lib/usageAccounting";
import { useRuntimeConfigVersion } from "../store";
import { ProviderSettings } from "./ProviderSettings";

type PlatformTab = "workbench" | "research" | "projects" | "runs" | "experiments" | "models";

const panel: React.CSSProperties = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.lg,
  padding: space.lg,
};

const field: React.CSSProperties = {
  minWidth: 180,
  flex: 1,
  border: `1px solid ${colors.border}`,
  borderRadius: radius.md,
  padding: `${space.sm} ${space.md}`,
  background: colors.surface,
  color: colors.text,
  fontFamily: typo.font,
  fontSize: typo.sm,
};

function parseScores(value: string): number[] {
  const scores = value
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map(Number);
  if (scores.some((item) => !Number.isFinite(item))) throw new Error("Scores must be numbers separated by commas.");
  return scores;
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ ...panel, padding: space.md }}>
      <div style={{ color: colors.textTertiary, fontSize: typo.xs }}>{label}</div>
      <div style={{ color: colors.text, fontSize: typo.xl, fontWeight: typo.semibold, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function Status({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const color = ["active", "running", "completed", "benchmarked", "healthy", "enabled"].includes(normalized)
    ? colors.success
    : ["failed", "rejected", "rolled_back"].includes(normalized)
      ? colors.danger
      : colors.textSecondary;
  return <span style={{ color, fontSize: typo.xs, fontWeight: typo.semibold, textTransform: "uppercase" }}>{value}</span>;
}

export function DeveloperPlatform({ modelsOnly = false, manageProviders = false, locale = "en", onOpenApprovals, onOpenCredentials, onDraftChange }: { modelsOnly?: boolean; manageProviders?: boolean; locale?: "en" | "zh"; onOpenApprovals?: () => void; onOpenCredentials?: () => void; onDraftChange?: (dirty: boolean) => void } = {}) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [tab, setTab] = useState<PlatformTab>(modelsOnly ? "models" : "workbench");
  const [modelSection, setModelSection] = useState("connections");
  const modelSectionsId = useId();
  const modelSections = [
    { id: "connections", label: t("Connections", "连接配置") },
    { id: "usage", label: t("Usage", "用量") },
    { id: "evidence", label: t("Run records", "运行记录") },
  ];
  const [overview, setOverview] = useState<DeveloperOverview | null>(null);
  const [projects, setProjects] = useState<DeveloperProject[]>([]);
  const [runs, setRuns] = useState<DeveloperRun[]>([]);
  const [experiments, setExperiments] = useState<DeveloperExperiment[]>([]);
  const [results, setResults] = useState<ExperimentResultView[]>([]);
  const [modelLab, setModelLab] = useState<ModelLabSnapshot | null>(null);
  const [modelLabLoading, setModelLabLoading] = useState(true);
  const [snapshotVersion, setSnapshotVersion] = useState(-1);
  const [usageDay, setUsageDay] = useState("");
  const configurationVersion = useRuntimeConfigVersion();
  const refreshSequence = useRef(0);
  const invalidateReads = useCallback(() => { refreshSequence.current++; }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [baselineName, setBaselineName] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [evaluationId, setEvaluationId] = useState("");
  const [baselineScores, setBaselineScores] = useState("");
  const [candidateScores, setCandidateScores] = useState("");

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    const controller = getConfig().url;
    const version = getRuntimeConfigVersion();
    setSnapshotVersion(version);
    setError("");
    setModelLab(null);
    setModelLabLoading(true);
    if (modelsOnly) {
      try {
        const models = await fetchModelLab(usageDay || undefined);
        if (sequence === refreshSequence.current && getConfig().url === controller && getRuntimeConfigVersion() === version) setModelLab(models);
      } catch {
        if (sequence === refreshSequence.current && getRuntimeConfigVersion() === version) setError("Model evidence and usage accounting are unavailable. Spend UNKNOWN.");
      } finally {
        if (sequence === refreshSequence.current && getRuntimeConfigVersion() === version) setModelLabLoading(false);
      }
      return;
    }
    const [overviewResult, projectsResult, runsResult, experimentsResult, modelsResult] = await Promise.allSettled([
      fetchDeveloperOverview(),
      fetchDeveloperProjects(),
      fetchDeveloperRuns(),
      fetchDeveloperExperiments(),
      fetchModelLab(usageDay || undefined),
    ]);
    if (sequence !== refreshSequence.current || getConfig().url !== controller || getRuntimeConfigVersion() !== version) return;
    if (overviewResult.status === "fulfilled") setOverview(overviewResult.value);
    if (projectsResult.status === "fulfilled") setProjects(projectsResult.value.projects);
    if (runsResult.status === "fulfilled") setRuns(runsResult.value.runs);
    if (experimentsResult.status === "fulfilled") {
      setExperiments(experimentsResult.value.experiments);
      setResults(experimentsResult.value.results);
    }
    if (modelsResult.status === "fulfilled") setModelLab(modelsResult.value);
    setModelLabLoading(false);
    const failure = [overviewResult, projectsResult, runsResult, experimentsResult, modelsResult]
      .find((item) => item.status === "rejected");
    if (failure?.status === "rejected") setError(errorMessage(failure.reason, "Developer Platform data is unavailable."));
  }, [usageDay, modelsOnly]);

  useEffect(() => {
    setOverview(null); setProjects([]); setRuns([]); setExperiments([]); setResults([]);
    void refresh();
    return invalidateReads;
  }, [refresh, configurationVersion, invalidateReads]);

  const createProject = async () => {
    if (!projectName.trim() || busy) return;
    setBusy(true); setError("");
    try {
      await createDeveloperProject(projectName.trim(), projectDescription.trim());
      setProjectName(""); setProjectDescription("");
      await refresh();
    } catch (cause) { setError(errorMessage(cause, "Project could not be created.")); } finally { setBusy(false); }
  };

  const actOnProject = async (projectId: string, action: string) => {
    if (busy) return;
    setBusy(true); setError("");
    try { await developerProjectAction(projectId, action); await refresh(); }
    catch (cause) { setError(errorMessage(cause, "Project action failed.")); } finally { setBusy(false); }
  };

  const createExperiment = async () => {
    if (!hypothesis.trim() || !baselineName.trim() || !candidateName.trim() || busy) return;
    setBusy(true); setError("");
    try {
      await createDeveloperExperiment({ hypothesis, baseline_name: baselineName, candidate_name: candidateName });
      setHypothesis(""); setBaselineName(""); setCandidateName("");
      await refresh();
    } catch (cause) { setError(errorMessage(cause, "Experiment could not be created.")); } finally { setBusy(false); }
  };

  const evaluateExperiment = async () => {
    if (!evaluationId || busy) return;
    setBusy(true); setError("");
    try {
      await evaluateDeveloperExperiment(evaluationId, parseScores(baselineScores), parseScores(candidateScores));
      setEvaluationId(""); setBaselineScores(""); setCandidateScores("");
      await refresh();
    } catch (cause) { setError(errorMessage(cause, "Experiment evaluation failed.")); } finally { setBusy(false); }
  };

  const tabs: Array<{ id: PlatformTab; label: string; count: number }> = [
    { id: "workbench", label: "Workbench", count: 0 },
    { id: "research", label: "Research", count: 0 },
    { id: "projects", label: "Projects", count: projects.length },
    { id: "runs", label: "Runs", count: runs.length },
    { id: "experiments", label: "Experiments", count: experiments.length },
    { id: "models", label: "Model Lab", count: snapshotVersion === configurationVersion ? modelLab?.models.length || 0 : 0 },
  ];

  return (
    <div style={{ height: modelsOnly ? "auto" : "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <header style={{ padding: `${space.lg} ${space.xl}`, background: colors.surface, borderBottom: `1px solid ${colors.borderLight}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: space.md, flexWrap: "wrap" }}>
          <div>
            <h1 style={{ margin: 0, color: colors.text, fontSize: typo.lg }}>{manageProviders ? (locale === "zh" ? "模型" : "Models") : modelsOnly ? "Model Lab" : "Developer Platform"}</h1>
            {!manageProviders && <p style={{ margin: `${space.xs} 0 0`, color: colors.textSecondary, fontSize: typo.sm }}>
              {manageProviders ? (locale === "zh" ? "服务商配置、模型测试及用量。" : "Provider configuration, model tests and usage.") : modelsOnly ? "Recorded model performance and usage accounting from the Controller." : "Governed editing, strict execution, real web evidence, canonical Runtime runs, experiments, and model evidence."}
            </p>}
          </div>
          {!manageProviders && <button onClick={() => void refresh()} disabled={busy} style={btnSecondary}>{t("Refresh", "刷新")}</button>}
        </div>
        {!modelsOnly && <div style={{ display: "flex", gap: space.xs, marginTop: space.lg, flexWrap: "wrap" }}>
          {tabs.map((item) => (
            <button key={item.id} onClick={() => setTab(item.id)} style={{
              border: "none", borderRadius: radius.md, cursor: "pointer", fontFamily: typo.font,
              padding: `${space.sm} ${space.md}`, background: tab === item.id ? colors.accentSoft : "transparent",
              color: tab === item.id ? colors.accent : colors.textSecondary, fontWeight: tab === item.id ? typo.semibold : typo.normal,
            }}>{item.label} <span style={{ color: colors.textTertiary }}>{item.count}</span></button>
          ))}
        </div>}
      </header>

      <div style={{ flex: 1, overflow: "auto", padding: space.xl }}>
        {overview && snapshotVersion === configurationVersion && <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(120px, 1fr))", gap: space.md, marginBottom: space.lg }}>
          <Metric label="Projects" value={`${overview.projects.active}/${overview.projects.total}`} />
          <Metric label="Active runs" value={overview.runs.active} />
          <Metric label="Benchmarked" value={overview.experiments.benchmarked} />
          <Metric label="Healthy models" value={`${overview.models.healthy}/${overview.models.total}`} />
        </div>}
        {error && <div style={{ ...panel, color: colors.danger, background: colors.dangerSoft, marginBottom: space.lg }}>{error}</div>}

        {tab === "workbench" && <DeveloperWorkbench />}
        {tab === "research" && <ResearchEvidence />}
        {tab === "projects" && <Projects projects={projects} busy={busy} name={projectName} description={projectDescription}
          setName={setProjectName} setDescription={setProjectDescription} onCreate={createProject} onAction={actOnProject} />}
        {tab === "runs" && <Runs runs={runs} />}
        {tab === "experiments" && <Experiments experiments={experiments} results={results} busy={busy}
          hypothesis={hypothesis} baselineName={baselineName} candidateName={candidateName}
          setHypothesis={setHypothesis} setBaselineName={setBaselineName} setCandidateName={setCandidateName}
          onCreate={createExperiment} evaluationId={evaluationId} setEvaluationId={setEvaluationId}
          baselineScores={baselineScores} candidateScores={candidateScores}
          setBaselineScores={setBaselineScores} setCandidateScores={setCandidateScores} onEvaluate={evaluateExperiment} />}
        {tab === "models" && <>
          {manageProviders && <>
            <nav role="tablist" aria-label={t("Model sections", "模型分类")} style={{ display: "flex", gap: space.sm, marginBottom: space.md, flexWrap: "wrap" }}>
              {modelSections.map((section, index) => <button key={section.id} id={`${modelSectionsId}-${section.id}`} role="tab" aria-selected={modelSection === section.id} aria-controls={`${modelSectionsId}-${section.id}-panel`} tabIndex={modelSection === section.id ? 0 : -1} style={modelSection === section.id ? btnPrimary : btnSecondary} onClick={() => setModelSection(section.id)} onKeyDown={event => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const next = event.key === "Home" ? 0 : event.key === "End" ? modelSections.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + modelSections.length) % modelSections.length;
                setModelSection(modelSections[next].id);
                event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
              }}>{section.label}</button>)}
            </nav>
            <section role="tabpanel" id={`${modelSectionsId}-connections-panel`} aria-labelledby={`${modelSectionsId}-connections`} hidden={modelSection !== "connections"}>
              <ProviderSettings key={configurationVersion} locale={locale} models={snapshotVersion === configurationVersion ? modelLab?.models || [] : []} modelsReady={snapshotVersion === configurationVersion && !!modelLab && !modelLabLoading} onChanged={refresh} onOpenApprovals={onOpenApprovals} onOpenCredentials={onOpenCredentials} onDraftChange={onDraftChange} />
            </section>
          </>}
          <section role={manageProviders ? "tabpanel" : undefined} id={`${modelSectionsId}-usage-panel`} aria-labelledby={manageProviders ? `${modelSectionsId}-usage` : undefined} hidden={manageProviders && modelSection !== "usage"}>
          <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: space.sm, marginBottom: space.md }}>
            <label style={{ color: colors.textSecondary, fontSize: typo.sm }}>{t("Usage day (UTC)", "用量日期（UTC）")} <input aria-label="Usage day (UTC)" type="date"
              value={usageDay || (snapshotVersion === configurationVersion ? modelLab?.usage_accounting?.day : "") || ""} onChange={event => setUsageDay(event.target.value)} style={field} /></label>
            <button onClick={() => setUsageDay("")} style={btnSecondary}>{t("Today", "今天")}</button>
          </div>
          <ModelLab locale={locale} view={manageProviders ? "usage" : "all"} data={snapshotVersion === configurationVersion ? modelLab : null} loading={modelLabLoading || snapshotVersion !== configurationVersion} />
          </section>
          {manageProviders && <section role="tabpanel" id={`${modelSectionsId}-evidence-panel`} aria-labelledby={`${modelSectionsId}-evidence`} hidden={modelSection !== "evidence"}>
            <ModelLab locale={locale} view="evidence" data={snapshotVersion === configurationVersion ? modelLab : null} loading={modelLabLoading || snapshotVersion !== configurationVersion} />
          </section>}
        </>}
      </div>
    </div>
  );
}

function Projects({ projects, busy, name, description, setName, setDescription, onCreate, onAction }: {
  projects: DeveloperProject[]; busy: boolean; name: string; description: string;
  setName: (value: string) => void; setDescription: (value: string) => void; onCreate: () => void;
  onAction: (id: string, action: string) => void;
}) {
  return <div style={{ display: "grid", gap: space.md }}>
    <section style={panel}>
      <div style={{ fontWeight: typo.semibold, color: colors.text, marginBottom: space.md }}>New project</div>
      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
        <input aria-label="Project name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Project name" style={field} />
        <input aria-label="Project description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Purpose or outcome" style={{ ...field, flex: 2 }} />
        <button onClick={onCreate} disabled={busy || !name.trim()} style={{ ...btnPrimary, opacity: busy || !name.trim() ? 0.55 : 1 }}>Create</button>
      </div>
    </section>
    {projects.length === 0 && <section style={panel}>No projects registered yet.</section>}
    {projects.map((project) => {
      const actions = project.status === "draft" ? ["start"] : project.status === "active" ? ["continue", "pause"] : project.status === "paused" ? ["resume"] : [];
      return <section key={project.project_id} style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
          <div><div style={{ color: colors.text, fontWeight: typo.semibold }}>{project.name}</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: 2 }}>{project.description || project.project_id}</div></div>
          <Status value={project.status} />
        </div>
        <div style={{ height: 5, borderRadius: radius.full, background: colors.borderLight, margin: `${space.md} 0` }}>
          <div style={{ width: `${Math.max(0, Math.min(100, project.progress?.progress_pct || 0))}%`, height: "100%", borderRadius: radius.full, background: colors.accent }} />
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
          <span style={{ color: colors.textTertiary, fontSize: typo.xs }}>{fixedNumber(project.progress?.progress_pct, 1)}% · {project.progress?.next_action || "No work plan"}</span>
          <div style={{ display: "flex", gap: space.sm }}>{actions.map((action) => <button key={action} disabled={busy} onClick={() => onAction(project.project_id, action)} style={btnSecondary}>{action}</button>)}</div>
        </div>
      </section>;
    })}
  </div>;
}

function Runs({ runs }: { runs: DeveloperRun[] }) {
  return <div style={{ display: "grid", gap: space.md }}>
    {runs.length === 0 && <section style={panel}>No persisted Runtime runs were found in this workspace.</section>}
    {runs.map((run) => <section key={run.run_id} style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: space.md }}>
        <div><code style={{ color: colors.text, fontFamily: typo.mono }}>{run.run_id}</code>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: 3 }}>{run.task_id || "Runtime request"}</div></div>
        <Status value={run.state} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(100px, 1fr))", gap: space.md, marginTop: space.md, color: colors.textSecondary, fontSize: typo.xs }}>
        <span>Progress {fixedNumber(run.progress_pct, 1)}%</span><span>Steps {run.completed_steps}/{run.total_steps}</span>
        <span>Events {run.last_sequence}</span><span>{run.updated_at ? new Date(run.updated_at).toLocaleString() : ""}</span>
      </div>
    </section>)}
  </div>;
}

function Experiments(props: {
  experiments: DeveloperExperiment[]; results: ExperimentResultView[]; busy: boolean;
  hypothesis: string; baselineName: string; candidateName: string;
  setHypothesis: (value: string) => void; setBaselineName: (value: string) => void; setCandidateName: (value: string) => void;
  onCreate: () => void; evaluationId: string; setEvaluationId: (value: string) => void;
  baselineScores: string; candidateScores: string; setBaselineScores: (value: string) => void; setCandidateScores: (value: string) => void;
  onEvaluate: () => void;
}) {
  return <div style={{ display: "grid", gap: space.md }}>
    <section style={panel}><div style={{ fontWeight: typo.semibold, color: colors.text, marginBottom: space.md }}>Define experiment</div>
      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
        <input aria-label="Hypothesis" value={props.hypothesis} onChange={(event) => props.setHypothesis(event.target.value)} placeholder="Testable hypothesis" style={{ ...field, flex: 2 }} />
        <input aria-label="Baseline" value={props.baselineName} onChange={(event) => props.setBaselineName(event.target.value)} placeholder="Baseline" style={field} />
        <input aria-label="Candidate" value={props.candidateName} onChange={(event) => props.setCandidateName(event.target.value)} placeholder="Candidate" style={field} />
        <button onClick={props.onCreate} disabled={props.busy} style={btnPrimary}>Create</button>
      </div>
    </section>
    {props.evaluationId && <section style={panel}>
      <div style={{ fontWeight: typo.semibold, color: colors.text }}>Record paired measurements</div>
      <p style={{ color: colors.textSecondary, fontSize: typo.sm }}>Nous computes significance, effect size, and confidence interval. It does not invent scores.</p>
      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
        <input aria-label="Baseline scores" value={props.baselineScores} onChange={(event) => props.setBaselineScores(event.target.value)} placeholder="Baseline: 0.72, 0.75, ..." style={field} />
        <input aria-label="Candidate scores" value={props.candidateScores} onChange={(event) => props.setCandidateScores(event.target.value)} placeholder="Candidate: 0.79, 0.81, ..." style={field} />
        <button onClick={props.onEvaluate} disabled={props.busy} style={btnPrimary}>Evaluate</button>
        <button onClick={() => props.setEvaluationId("")} style={btnSecondary}>Cancel</button>
      </div>
    </section>}
    {props.experiments.length === 0 && <section style={panel}>No experiments defined yet.</section>}
    {props.experiments.map((experiment) => {
      const latest = props.results.find((item) => item.experiment_id === experiment.experiment_id);
      return <section key={experiment.experiment_id} style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: space.md }}><div>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>{experiment.hypothesis}</div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: 3 }}>{experiment.baseline_name} → {experiment.candidate_name}</div>
        </div><Status value={experiment.state} /></div>
        {latest && <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(100px, 1fr))", gap: space.md, marginTop: space.md, fontSize: typo.sm, color: colors.textSecondary }}>
          <span>Δ {fixedNumber(latest.improvement, 4)}</span><span>p {fixedNumber(latest.p_value, 4)}</span>
          <span>effect {fixedNumber(latest.effect_size, 3)}</span><span>n {latest.sample_size}</span>
        </div>}
        <button onClick={() => props.setEvaluationId(experiment.experiment_id)} style={{ ...btnSecondary, marginTop: space.md }}>Add measurements</button>
      </section>;
    })}
  </div>;
}

export function ModelLab({ data, loading = false, locale = "en", view = "all" }: { data: ModelLabSnapshot | null; loading?: boolean; locale?: "en" | "zh"; view?: "all" | "usage" | "evidence" }) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  if (!data) return <section role={loading ? "status" : "alert"} style={panel}>{loading ? t("Loading model evidence and usage accounting…", "正在读取模型记录与用量…") : t("Model evidence and usage accounting are unavailable. Spend UNKNOWN.", "无法读取模型与用量记录，费用 UNKNOWN。")}</section>;
  const accounting = data.usage_accounting_status === "available" && isUsageAccountingSummary(data.usage_accounting)
    ? data.usage_accounting : null;
  return <div style={{ display: "grid", gap: space.md }}>
    {view !== "evidence" && <section style={panel}>
      <h2 style={{ marginTop: 0, fontSize: typo.md, color: colors.text }}>{t("Model usage and cost", "模型用量与费用")}</h2>
      {accounting ? <UsageAccounting summary={accounting} locale={locale} /> : <p role="alert">{t("Usage accounting unavailable. Spend UNKNOWN.", "用量记录不可用，费用 UNKNOWN。")}</p>}
    </section>}
    {view !== "usage" && <><section style={{ ...panel, color: colors.textSecondary, fontSize: typo.sm }}>
      {t("Performance evidence", "性能记录")}: <Status value={data.evidence_status} /> · {data.recent_observations.length} {t("recorded observations", "条观察记录")}
    </section>
    {data.models.length === 0 && <section style={panel}>{t("No models configured.", "尚未配置模型。")}</section>}
    {data.models.map((model) => {
      const ranking = data.rankings.find((item) => item.model_id === model.model_id);
      return <section key={model.model_id} style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: space.md }}><div>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>{model.display_name}</div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: 3 }}>{model.provider_id} · {model.endpoint_type}</div>
        </div><Status value={model.health} /></div>
        <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: space.md }}>{model.capabilities.join(" · ") || t("No declared capabilities", "未声明能力")}</div>
        {ranking ? <div style={{ display: "flex", flexWrap: "wrap", gap: space.md, marginTop: space.md, color: colors.textSecondary, fontSize: typo.sm }}>
          <span>{t("Samples", "样本")} {usageNumber(ranking.sample_count)}</span><span>{t("Success", "成功率")} {typeof ranking.success_rate === "number" && Number.isFinite(ranking.success_rate) ? `${(ranking.success_rate * 100).toFixed(1)}%` : "UNKNOWN"}</span>
          <span>{t("Latency", "延迟")} {usageNumber(ranking.avg_latency_ms)} ms</span>
        </div> : <p style={{ color: colors.textTertiary, fontSize: typo.sm }}>{t("No performance observations for this model.", "此模型暂无性能记录。")}</p>}
      </section>;
    })}</>}
  </div>;
}
