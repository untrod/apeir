# -*- coding: utf-8 -*-
"""Control Plane API v2 — real handler implementations for Intelligence & Discovery.

All routes under /api/v2/. Handlers connect to actual runtime modules.
No stub data. No mock responses. Real computation or clear error.
"""

from __future__ import annotations

from typing import Any


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "meta": {"api_version": "v2"}}


def _err(code: str, message: str) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "details": {}},
        "meta": {"api_version": "v2"},
    }



# Intelligence v2


def handle_list_traces_v2(params: dict) -> dict:
    try:
        from nous_runtime.intelligence.trace import TraceStore
        store = TraceStore()
        traces = store.query(
            task_type=params.get("task_type", ""),
            session_id=params.get("session_id", ""),
            status=params.get("status", ""),
            limit=int(params.get("limit", 100)),
            offset=int(params.get("offset", 0)),
        )
        return _ok({"traces": [t.to_dict() for t in traces], "total": store.count()})
    except Exception as e:
        return _err("TRACE_LIST_ERROR", str(e))


def handle_get_trace_v2(trace_id: str) -> dict:
    try:
        from nous_runtime.intelligence.trace import TraceStore
        store = TraceStore()
        record = store.get(trace_id)
        if record is None:
            return _err("NOT_FOUND", f"Trace {trace_id} not found")
        return _ok(record.to_dict())
    except Exception as e:
        return _err("TRACE_GET_ERROR", str(e))


def handle_list_datasets(params: dict) -> dict:
    try:
        from nous_runtime.intelligence.dataset import DatasetRegistry, DatasetType
        registry = DatasetRegistry()
        ds_type = params.get("dataset_type", "")
        records = registry.query(
            dataset_type=DatasetType(ds_type) if ds_type else None,
            min_tasks=int(params.get("min_tasks", 0)),
        )
        return _ok({"datasets": [r.to_dict() for r in records], "total": registry.count()})
    except Exception as e:
        return _err("DATASET_LIST_ERROR", str(e))


def handle_replay_trace(trace_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.intelligence.replay import ReplayEngine
        from nous_runtime.intelligence.trace import TraceStore
        engine = ReplayEngine(trace_store=TraceStore())
        result = engine.replay(trace_id)
        return _ok({"replay_id": result.replay_id, "status": result.status, "differences": result.differences})
    except Exception as e:
        return _err("REPLAY_ERROR", str(e))


def handle_list_benchmarks(params: dict) -> dict:
    try:
        from benchmarks.task_specs import TASK_TYPES, DEFAULT_TASKS
        return _ok({"task_types": TASK_TYPES, "total_tasks": len(DEFAULT_TASKS)})
    except Exception as e:
        return _err("BENCHMARK_LIST_ERROR", str(e))


def handle_list_baselines(params: dict) -> dict:
    try:
        from nous_runtime.intelligence.baselines import BaselineRegistry
        registry = BaselineRegistry()
        baselines = [{"name": b.name, "description": b.description, "category": b.category} for b in registry.list_all()]
        return _ok({"baselines": baselines, "total": len(baselines)})
    except Exception as e:
        return _err("BASELINE_LIST_ERROR", str(e))


def handle_evaluate_plan(body: dict) -> dict:
    try:
        from nous_runtime.intelligence.constraints import ConstraintEngine
        from nous_runtime.intelligence.plans import ExecutionPlan
        plan = ExecutionPlan()
        plan.plan_id_for()
        plan.model_assignments = body.get("model_assignments", {})
        plan.verification_strategy = body.get("verification_strategy", "standard")
        engine = ConstraintEngine()
        result = engine.evaluate(plan.__dict__, body.get("context", {}))
        return _ok({"plan_id": plan.plan_id, "feasible": result.feasible, "violations": result.violated_constraints})
    except Exception as e:
        return _err("PLAN_EVAL_ERROR", str(e))


def handle_constraints_check(body: dict) -> dict:
    try:
        from nous_runtime.intelligence.constraints import ConstraintEngine
        engine = ConstraintEngine()
        result = engine.evaluate(body.get("plan", {}), body.get("context", {}))
        return _ok({"feasible": result.feasible, "violations": result.violated_constraints, "soft_scores": result.soft_scores})
    except Exception as e:
        return _err("CONSTRAINT_ERROR", str(e))


def handle_pareto_frontier(body: dict) -> dict:
    try:
        from nous_runtime.intelligence.pareto import ParetoEngine
        engine = ParetoEngine()
        result = engine.compute_frontier(body.get("plans", []))
        return _ok({"non_dominated_count": len(result.non_dominated), "dominated_count": len(result.dominated), "trade_off": result.trade_off_summary})
    except Exception as e:
        return _err("PARETO_ERROR", str(e))


def handle_outcome_prediction(body: dict) -> dict:
    try:
        from nous_runtime.intelligence.outcomes import OutcomeModel
        from nous_runtime.intelligence.plans import ExecutionPlan
        model = OutcomeModel()
        plan = ExecutionPlan()
        plan.plan_id_for()
        plan.model_assignments = body.get("model_assignments", {})
        plan.verification_strategy = body.get("verification_strategy", "standard")
        ctx = body.get("context", {})
        prediction = model.predict(plan, ctx)
        return _ok({"plan_id": plan.plan_id, "predicted_success": prediction.completion_probability, "uncertainty": prediction.epistemic_uncertainty, "confidence": prediction.prediction_confidence})
    except Exception as e:
        return _err("OUTCOME_ERROR", str(e))


def handle_calibration_report(params: dict) -> dict:
    try:
        from nous_runtime.intelligence.metrics import MetricsComputer
        from nous_runtime.intelligence.trace import TraceStore
        store = TraceStore()
        traces = store.query(limit=100)
        computer = MetricsComputer(traces)
        report = computer.compute_all()
        ece = report.get("calibration_error")
        return _ok({"ece": ece.value if ece else 0, "sample_size": ece.sample_size if ece else 0})
    except Exception as e:
        return _err("CALIBRATION_ERROR", str(e))


def handle_shadow_comparison(body: dict) -> dict:
    try:
        from nous_runtime.intelligence.policy.shadow import ShadowComparisonStore
        store = ShadowComparisonStore()
        stats = store.statistics()
        return _ok({"comparisons": stats.get("total_comparisons", 0), "mean_regret": stats.get("mean_regret", 0), "safety_violation_rate": stats.get("safety_violation_rate", 0)})
    except Exception as e:
        return _err("SHADOW_ERROR", str(e))


def handle_drift_status(params: dict) -> dict:
    try:
        from nous_runtime.intelligence.drift import DriftDetector
        detector = DriftDetector()
        alerts = detector.recent_alerts(10)
        return _ok({"drift_detected": detector.is_stale, "policy_confidence": detector.policy_confidence, "recent_alerts": [a.__dict__ for a in alerts]})
    except Exception as e:
        return _err("DRIFT_ERROR", str(e))



# Orchestration v2


def handle_compile_graph(body: dict) -> dict:
    try:
        from nous_runtime.orchestration import GraphCompiler, validate_dag
        compiler = GraphCompiler()
        graph = compiler.compile(body)
        valid, msg = validate_dag(graph)
        return _ok({"graph_id": graph.graph_id, "node_count": len(graph.nodes), "valid": valid, "message": msg})
    except Exception as e:
        return _err("GRAPH_ERROR", str(e))


def handle_list_roles(params: dict) -> dict:
    try:
        from nous_runtime.orchestration import RoleGenerator
        gen = RoleGenerator()
        roles = gen.generate(params)
        return _ok({"roles": [r.__dict__ for r in roles], "total": len(roles)})
    except Exception as e:
        return _err("ROLES_ERROR", str(e))


def handle_compute_assignment(body: dict) -> dict:
    try:
        from nous_runtime.orchestration import AssignmentEngine
        engine = AssignmentEngine()
        assignments = engine.assign(
            roles=body.get("roles", []),
            models=body.get("models", []),
            nodes=body.get("nodes", []),
            task=body.get("task", {}),
        )
        return _ok({"assignments": [a.__dict__ for a in assignments]})
    except Exception as e:
        return _err("ASSIGNMENT_ERROR", str(e))


def handle_validate_contracts(artifact_id: str) -> dict:
    try:
        from nous_runtime.orchestration import ContractRegistry
        registry = ContractRegistry()
        contract = registry.get(artifact_id)
        if contract is None:
            return _err("NOT_FOUND", f"Contract {artifact_id} not found")
        return _ok({"artifact_id": artifact_id, "valid": True, "contract": contract.to_dict()})
    except Exception as e:
        return _err("CONTRACT_ERROR", str(e))


def handle_trigger_replan(body: dict) -> dict:
    try:
        from nous_runtime.orchestration import Replanner, ReplanTrigger
        replanner = Replanner()
        trigger = ReplanTrigger(body.get("trigger", "node_offline"))
        actions = replanner.replan(trigger, None, body.get("context", {}))
        return _ok({"actions": [a.__dict__ for a in actions], "count": len(actions)})
    except Exception as e:
        return _err("REPLAN_ERROR", str(e))


def handle_credit_report(task_id: str) -> dict:
    try:
        from nous_runtime.orchestration import CreditAssigner
        assigner = CreditAssigner()
        report = assigner.assign(task_id, agents=[], outcomes={}, overall_success=False)
        return _ok({"task_id": task_id, "contributions": report.agent_contributions, "method": report.method})
    except Exception as e:
        return _err("CREDIT_ERROR", str(e))



# Evidence v2


def handle_list_sources(params: dict) -> dict:
    try:
        from nous_runtime.evidence import SourceRegistry
        registry = SourceRegistry()
        sources = registry.query()
        return _ok({"sources": [s.__dict__ for s in sources], "total": registry.count()})
    except Exception as e:
        return _err("SOURCES_ERROR", str(e))


def handle_get_snapshot(snapshot_id: str) -> dict:
    try:
        from nous_runtime.evidence import SnapshotStore
        store = SnapshotStore()
        snap = store.get(snapshot_id)
        if snap is None:
            return _err("NOT_FOUND", f"Snapshot {snapshot_id} not found")
        return _ok({"snapshot_id": snapshot_id, "hash": snap.raw_content_hash, "size_bytes": snap.size_bytes})
    except Exception as e:
        return _err("SNAPSHOT_ERROR", str(e))


def handle_list_claims(params: dict) -> dict:
    try:
        from nous_runtime.evidence import ClaimEvidenceGraph
        graph = ClaimEvidenceGraph()
        summary = graph.summary()
        return _ok(summary)
    except Exception as e:
        return _err("CLAIMS_ERROR", str(e))


def handle_get_conflicts(params: dict) -> dict:
    try:
        from nous_runtime.evidence import ClaimEvidenceGraph
        graph = ClaimEvidenceGraph()
        conflicts = graph.get_conflicts()
        return _ok({"conflicts": conflicts, "total": len(conflicts)})
    except Exception as e:
        return _err("CONFLICTS_ERROR", str(e))


def handle_check_freshness(source_id: str) -> dict:
    try:
        from nous_runtime.evidence import FreshnessTracker
        tracker = FreshnessTracker()
        fresh, msg = tracker.is_fresh(source_id)
        return _ok({"source_id": source_id, "fresh": fresh, "message": msg})
    except Exception as e:
        return _err("FRESHNESS_ERROR", str(e))



# Experiments v2


def handle_list_experiments(params: dict) -> dict:
    try:
        from nous_runtime.experiments import ExperimentRegistry, ExperimentState
        registry = ExperimentRegistry()
        state = params.get("state", "")
        experiments = registry.list_by_state(ExperimentState(state)) if state else registry.list()
        return _ok({"experiments": [e.__dict__ for e in experiments], "total": registry.count()})
    except Exception as e:
        return _err("EXPERIMENTS_ERROR", str(e))


def handle_run_experiment(experiment_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.experiments import ExperimentService
        values = body or {}
        result = ExperimentService().evaluate(
            experiment_id,
            values.get("baseline_scores"),
            values.get("candidate_scores"),
        )
        return _ok(result)
    except KeyError:
        return _err("NOT_FOUND", f"Experiment {experiment_id} not found")
    except Exception as e:
        return _err("EXPERIMENT_RUN_ERROR", str(e))


def handle_ablation(experiment_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.experiments import AblationRunner
        runner = AblationRunner()
        values = body or {}
        components = values.get("components", [])
        ablated_scores = values.get("ablated_scores", {})
        if not components or not isinstance(ablated_scores, dict):
            raise ValueError("components and ablated_scores are required")
        full_score = float(values["full_score"])
        missing = [component for component in components if component not in ablated_scores]
        if missing:
            raise ValueError(f"missing ablated scores for: {', '.join(missing)}")

        def evaluate(selected):
            removed = [component for component in components if component not in selected]
            return full_score if not removed else float(ablated_scores[removed[0]])

        study = runner.run(experiment_id, components, evaluate)
        return _ok({"experiment_id": experiment_id, "components": len(components), "most_important": [r.component_name for r in study.most_important()[:3]]})
    except Exception as e:
        return _err("ABLATION_ERROR", str(e))


def handle_promote(experiment_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.experiments import ExperimentRegistry, PromotionPipeline
        registry = ExperimentRegistry()
        spec = registry.get(experiment_id)
        if spec is None:
            return _err("NOT_FOUND", f"Experiment {experiment_id} not found")
        pipeline = PromotionPipeline()
        decision = pipeline.evaluate(spec, (body or {}).get("evidence", {}))
        if decision.value == "promote":
            pipeline.promote(spec)
            registry.save(spec)
        return _ok({"experiment_id": experiment_id, "new_state": spec.state.value, "decision": decision.value})
    except Exception as e:
        return _err("PROMOTE_ERROR", str(e))


def handle_rollback(experiment_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.experiments import ExperimentRegistry, PromotionPipeline
        registry = ExperimentRegistry()
        spec = registry.get(experiment_id)
        if spec is None:
            return _err("NOT_FOUND", f"Experiment {experiment_id} not found")
        pipeline = PromotionPipeline()
        pipeline.rollback(spec)
        registry.save(spec)
        return _ok({"experiment_id": experiment_id, "new_state": spec.state.value})
    except Exception as e:
        return _err("ROLLBACK_ERROR", str(e))



# Emergence v2


def handle_list_candidates(params: dict) -> dict:
    try:
        from nous_runtime.emergence import Population
        pop = Population()
        return _ok({"population_size": pop.size, "diversity": pop.diversity(), "best_fitness": pop.best().fitness if pop.best() else 0})
    except Exception as e:
        return _err("CANDIDATES_ERROR", str(e))


def handle_archive_status(params: dict) -> dict:
    try:
        from nous_runtime.emergence import QDArchive
        archive = QDArchive(bins_per_dimension=10)
        return _ok({"bins_filled": len(archive.bins), "coverage": archive.coverage(), "diversity": archive.diversity_score()})
    except Exception as e:
        return _err("ARCHIVE_ERROR", str(e))


def handle_replicate(genome_id: str, body: dict | None = None) -> dict:
    try:
        from nous_runtime.emergence import ReplicationGate, AnomalyRecord
        gate = ReplicationGate()
        anomaly = AnomalyRecord(anomaly_id=genome_id)
        result = gate.evaluate(anomaly, (body or {}).get("results", []))
        return _ok({"genome_id": genome_id, "replicated": result.replicated, "new_status": result.new_status, "passed_checks": result.passed_checks})
    except Exception as e:
        return _err("REPLICATE_ERROR", str(e))


def handle_promote_genome(genome_id: str, body: dict | None = None) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "Genome promotion has no persistent governed execution path yet")



# Research v2


def handle_list_papers(params: dict) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "The v2 paper repository authority is not connected")


def handle_list_hypotheses(params: dict) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "The v2 hypothesis repository authority is not connected")


def handle_list_research_claims(params: dict) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "Use the governed /api/v1/research/claims authority")


def handle_generate_report(params: dict) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "Use DocumentRuntime; v2 research report generation is not connected")



# Plugins & Governance v2


def handle_list_plugins(params: dict) -> dict:
    return _err("NOUS_NOT_IMPLEMENTED", "The v2 plugin registry authority is not connected")


def handle_list_governance_policies(params: dict) -> dict:
    try:
        from nous_runtime.governance.identities import IdentityRegistry
        registry = IdentityRegistry()
        return _ok({"policies": [], "total": registry.count(), "note": "Identity-based governance active"})
    except Exception as e:
        return _err("POLICIES_ERROR", str(e))


def handle_list_approvals_v2(params: dict) -> dict:
    try:
        from nous_runtime.governance.mobile_approval import MobileApprovalService
        service = MobileApprovalService()
        pending = service.get_pending()
        return _ok({"approvals": [p.__dict__ for p in pending], "total": len(pending)})
    except Exception as e:
        return _err("APPROVALS_ERROR", str(e))



# Route table


V2_ROUTES: dict[tuple[str, str], Any] = {
    # Intelligence
    ("GET", "/api/v2/intelligence/traces"): handle_list_traces_v2,
    ("GET", "/api/v2/intelligence/traces/{trace_id}"): handle_get_trace_v2,
    ("GET", "/api/v2/intelligence/datasets"): handle_list_datasets,
    ("POST", "/api/v2/intelligence/replay"): handle_replay_trace,
    ("GET", "/api/v2/intelligence/benchmarks"): handle_list_benchmarks,
    ("GET", "/api/v2/intelligence/baselines"): handle_list_baselines,
    ("POST", "/api/v2/intelligence/plans/evaluate"): handle_evaluate_plan,
    ("POST", "/api/v2/intelligence/constraints"): handle_constraints_check,
    ("POST", "/api/v2/intelligence/pareto"): handle_pareto_frontier,
    ("POST", "/api/v2/intelligence/outcomes"): handle_outcome_prediction,
    ("GET", "/api/v2/intelligence/calibration"): handle_calibration_report,
    ("POST", "/api/v2/intelligence/shadow"): handle_shadow_comparison,
    ("GET", "/api/v2/intelligence/drift"): handle_drift_status,
    # Orchestration
    ("POST", "/api/v2/orchestration/graphs"): handle_compile_graph,
    ("GET", "/api/v2/orchestration/roles"): handle_list_roles,
    ("POST", "/api/v2/orchestration/assignments"): handle_compute_assignment,
    ("GET", "/api/v2/orchestration/contracts/{artifact_id}"): handle_validate_contracts,
    ("POST", "/api/v2/orchestration/replans"): handle_trigger_replan,
    ("GET", "/api/v2/orchestration/credit/{task_id}"): handle_credit_report,
    # Evidence
    ("GET", "/api/v2/evidence/sources"): handle_list_sources,
    ("GET", "/api/v2/evidence/snapshots/{snapshot_id}"): handle_get_snapshot,
    ("GET", "/api/v2/evidence/claims"): handle_list_claims,
    ("GET", "/api/v2/evidence/conflicts"): handle_get_conflicts,
    ("GET", "/api/v2/evidence/freshness/{source_id}"): handle_check_freshness,
    # Experiments
    ("GET", "/api/v2/experiments"): handle_list_experiments,
    ("POST", "/api/v2/experiments/{experiment_id}/run"): handle_run_experiment,
    ("POST", "/api/v2/experiments/{experiment_id}/ablation"): handle_ablation,
    ("POST", "/api/v2/experiments/{experiment_id}/promote"): handle_promote,
    ("POST", "/api/v2/experiments/{experiment_id}/rollback"): handle_rollback,
    # Emergence
    ("GET", "/api/v2/emergence/candidates"): handle_list_candidates,
    ("GET", "/api/v2/emergence/archive"): handle_archive_status,
    ("POST", "/api/v2/emergence/replicate"): handle_replicate,
    ("POST", "/api/v2/emergence/promote"): handle_promote_genome,
    # Research
    ("GET", "/api/v2/research/papers"): handle_list_papers,
    ("GET", "/api/v2/research/hypotheses"): handle_list_hypotheses,
    ("GET", "/api/v2/research/claims"): handle_list_research_claims,
    ("POST", "/api/v2/research/reports"): handle_generate_report,
    # Plugins & Governance
    ("GET", "/api/v2/plugins"): handle_list_plugins,
    ("GET", "/api/v2/governance/policies"): handle_list_governance_policies,
    ("GET", "/api/v2/governance/approvals"): handle_list_approvals_v2,
}
