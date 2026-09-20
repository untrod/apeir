# -*- coding: utf-8 -*-
"""Tests for Metrics Computer."""



class TestMetricsComputer:
    def test_compute_all_with_empty_traces(self):
        from nous_runtime.intelligence.metrics import MetricsComputer
        computer = MetricsComputer([])
        report = computer.compute_all()
        assert report.total_traces == 0
        assert len(report.metrics) == 20  # all metrics defined

    def test_compute_task_success_rate(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        from nous_runtime.intelligence.metrics import MetricsComputer

        traces = []
        for i in range(8):
            t = ExecutionTraceRecord.new(task_type="test")
            t.outcome.final_status = "success"
            traces.append(t)
        for i in range(2):
            t = ExecutionTraceRecord.new(task_type="test")
            t.outcome.final_status = "failure"
            traces.append(t)

        computer = MetricsComputer(traces)
        report = computer.compute_all()
        success_rate = report.get("task_success_rate")
        assert success_rate is not None
        assert success_rate.value == 0.8
        assert success_rate.sample_size == 10

    def test_compute_verified_success_rate(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        from nous_runtime.intelligence.metrics import MetricsComputer

        traces = []
        for i in range(5):
            t = ExecutionTraceRecord.new(task_type="test")
            t.outcome.final_status = "success"
            t.outcome.verification_status = "pass"
            traces.append(t)
        for i in range(3):
            t = ExecutionTraceRecord.new(task_type="test")
            t.outcome.final_status = "success"
            t.outcome.verification_status = "fail"
            traces.append(t)

        computer = MetricsComputer(traces)
        report = computer.compute_all()
        verified = report.get("verified_success_rate")
        assert verified is not None
        assert verified.value == 5 / 8

    def test_compute_false_completion_rate(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        from nous_runtime.intelligence.metrics import MetricsComputer

        traces = []
        # 5 successes with pass
        for i in range(5):
            t = ExecutionTraceRecord.new()
            t.outcome.final_status = "success"
            t.outcome.verification_status = "pass"
            traces.append(t)
        # 2 successes but verification failed (false completion)
        for i in range(2):
            t = ExecutionTraceRecord.new()
            t.outcome.final_status = "success"
            t.outcome.verification_status = "fail"
            traces.append(t)

        computer = MetricsComputer(traces)
        report = computer.compute_all()
        false_comp = report.get("false_completion_rate")
        assert false_comp is not None
        assert false_comp.value == 2 / 7  # 2 false / 7 total successes

    def test_compute_latency_percentiles(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        from nous_runtime.intelligence.metrics import MetricsComputer

        traces = []
        for lat in [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
            t = ExecutionTraceRecord.new()
            t.outcome.latency_ms = lat
            traces.append(t)

        computer = MetricsComputer(traces)
        report = computer.compute_all()
        p50 = report.get("latency_p50_ms")
        p95 = report.get("latency_p95_ms")
        assert p50 is not None
        assert p95 is not None
        assert p50.value == 550.0  # median of 10 sorted values

    def test_compute_human_intervention_rate(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        from nous_runtime.intelligence.metrics import MetricsComputer

        traces = []
        for i in range(7):
            t = ExecutionTraceRecord.new()
            t.outcome.human_intervention = (i < 2)  # 2 interventions
            traces.append(t)

        computer = MetricsComputer(traces)
        report = computer.compute_all()
        hi_rate = report.get("human_intervention_rate")
        assert hi_rate is not None
        assert hi_rate.value == 2 / 7

    def test_all_metrics_have_definitions(self):
        from nous_runtime.intelligence.metrics import METRIC_DEFINITIONS
        required = [
            "task_success_rate", "verified_success_rate", "false_completion_rate",
            "recovery_success_rate", "human_intervention_rate", "cost_per_verified_task",
            "mean_completion_time_ms", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
            "artifact_integrity_rate", "event_loss_rate", "duplicate_execution_rate",
            "node_utilization", "provider_failure_rate", "repeatability_rate",
            "constraint_violation_rate", "safety_violation_rate", "routing_regret",
            "calibration_error",
        ]
        for metric in required:
            assert metric in METRIC_DEFINITIONS, f"Missing definition for {metric}"
            md = METRIC_DEFINITIONS[metric]
            assert md.formula != "", f"Missing formula for {metric}"
            assert md.data_source != "", f"Missing data source for {metric}"
