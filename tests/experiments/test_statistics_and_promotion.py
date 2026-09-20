# -*- coding: utf-8 -*-
"""Tests for experiments: statistics, promotion, ablation."""



class TestStatisticalAnalyzer:
    def test_compare_significant_difference(self):
        from nous_runtime.experiments import StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()
        baseline = [0.7] * 30 + [0.8] * 30 + [0.75] * 40
        candidate = [0.8] * 30 + [0.9] * 30 + [0.85] * 40
        result = analyzer.compare(baseline, candidate)
        assert result.mean_candidate > result.mean_baseline
        assert result.effect_size > 0

    def test_compare_equal_performance(self):
        from nous_runtime.experiments import StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()
        same = [0.8] * 100
        result = analyzer.compare(same, same)
        assert abs(result.effect_size) < 0.01

    def test_small_sample_handled(self):
        from nous_runtime.experiments import StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()
        result = analyzer.compare([0.5], [0.6])
        assert result.sample_size == 1

    def test_bonferroni_correction(self):
        from nous_runtime.experiments import StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()
        p_values = [0.01, 0.02, 0.03, 0.50]
        corrected = analyzer.multiple_comparison_correction(p_values, method="bonferroni")
        assert len(corrected) == 4
        assert corrected[0] == min(1.0, 0.01 * 4)

    def test_power_analysis(self):
        from nous_runtime.experiments import StatisticalAnalyzer
        analyzer = StatisticalAnalyzer()
        n = analyzer.power_analysis(effect_size=0.5)
        assert n >= 5


class TestPromotionPipeline:
    def test_propose_to_sandbox(self):
        from nous_runtime.experiments import ExperimentSpec, ExperimentState, PromotionPipeline
        spec = ExperimentSpec(experiment_id="exp_1", state=ExperimentState.PROPOSED)
        pipeline = PromotionPipeline()
        evidence = {"experiment_spec": True, "hypothesis": True, "baseline_defined": True}
        decision = pipeline.evaluate(spec, evidence)
        assert decision.value == "promote"

    def test_insufficient_evidence_retains(self):
        from nous_runtime.experiments import ExperimentSpec, ExperimentState, PromotionPipeline
        spec = ExperimentSpec(experiment_id="exp_2", state=ExperimentState.BENCHMARKED)
        pipeline = PromotionPipeline()
        decision = pipeline.evaluate(spec, {})
        assert decision.value == "retain"

    def test_rollback(self):
        from nous_runtime.experiments import ExperimentSpec, ExperimentState, PromotionPipeline
        spec = ExperimentSpec(experiment_id="exp_3", state=ExperimentState.CANARY)
        pipeline = PromotionPipeline()
        pipeline.rollback(spec)
        assert spec.state == ExperimentState.ROLLED_BACK

    def test_direct_promotion_cannot_bypass_evidence_gate(self):
        from nous_runtime.experiments import ExperimentSpec, ExperimentState, PromotionPipeline

        spec = ExperimentSpec(
            experiment_id="exp_production",
            state=ExperimentState.APPROVED,
        )
        pipeline = PromotionPipeline()

        assert pipeline.promote(spec) is ExperimentState.APPROVED
        assert pipeline.promote(
            spec,
            {
                "safety_envelope_version": "safety-v1",
                "governance_decision": "governance-1",
                "rollback_plan": "rollback-1",
                "sample_size": 200,
                "human_approved": True,
            },
        ) is ExperimentState.PRODUCTION

    def test_production_promotion_requires_safety_and_human_approval(self):
        from nous_runtime.experiments import ExperimentSpec, ExperimentState, PromotionPipeline

        spec = ExperimentSpec(
            experiment_id="exp_unsafe",
            state=ExperimentState.APPROVED,
        )
        decision = PromotionPipeline().evaluate(
            spec,
            {
                "governance_decision": "governance-1",
                "rollback_plan": "rollback-1",
                "sample_size": 500,
                "human_approved": True,
            },
        )

        assert decision.value == "retain"


class TestAblationRunner:
    def test_run_ablation(self):
        from nous_runtime.experiments import AblationRunner
        runner = AblationRunner()
        study = runner.run("exp_test", ["a", "b", "c"], lambda comps: 1.0 - 0.05 * (3 - len(comps)))
        assert len(study.results) == 3
        most = study.most_important()
        assert len(most) == 3
