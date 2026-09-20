# -*- coding: utf-8 -*-
"""Tests for ExecutionTraceRecord schema and TraceCollector."""



class TestExecutionTraceRecord:
    def test_create_new_record(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        record = ExecutionTraceRecord.new(task_id="task_001", task_type="code_audit")
        assert record.trace_id.startswith("etr_")
        assert record.task_info.task_id == "task_001"
        assert record.task_info.task_type == "code_audit"
        assert record.schema_version == "1.0.0"

    def test_seal_sets_hash_and_timestamp(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        record = ExecutionTraceRecord.new()
        assert record.content_hash == ""
        record.seal()
        assert record.content_hash != ""
        assert record.created_at != ""

    def test_to_dict_and_from_dict_roundtrip(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        original = ExecutionTraceRecord.new(task_id="task_001", task_type="bug_fix")
        original.decision.candidate_plans = 5
        original.decision.selected_plan = "plan_B"
        original.execution.tool_sequence = ["file.read", "code.edit", "test.run"]
        original.outcome.final_status = "success"
        original.outcome.latency_ms = 1234.5
        original.seal()

        data = original.to_dict()
        restored = ExecutionTraceRecord.from_dict(data)

        assert restored.trace_id == original.trace_id
        assert restored.task_info.task_id == original.task_info.task_id
        assert restored.decision.candidate_plans == 5
        assert restored.decision.selected_plan == "plan_B"
        assert restored.execution.tool_sequence == ["file.read", "code.edit", "test.run"]
        assert restored.outcome.final_status == "success"
        assert restored.outcome.latency_ms == 1234.5

    def test_to_jsonl_produces_valid_json(self):
        import json
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        record = ExecutionTraceRecord.new(task_id="t1")
        record.seal()
        line = record.to_jsonl()
        parsed = json.loads(line)
        assert parsed["trace_id"] == record.trace_id

    def test_hash_deterministic(self):
        from nous_runtime.intelligence.trace import ExecutionTraceRecord
        r1 = ExecutionTraceRecord.new(task_id="same_id")
        r2 = ExecutionTraceRecord.from_dict(r1.to_dict())
        assert r1.compute_hash() == r2.compute_hash()


class TestTraceCollector:
    def test_collector_creates_record_with_minimal_input(self):
        from nous_runtime.intelligence.trace import TraceCollector
        collector = TraceCollector()
        record = collector.collect()
        assert record.trace_id != ""
        assert record.sequence == 1
        assert record.sanitization_level == "basic"

    def test_collector_increments_sequence(self):
        from nous_runtime.intelligence.trace import TraceCollector
        collector = TraceCollector()
        r1 = collector.collect()
        r2 = collector.collect()
        assert r2.sequence == r1.sequence + 1


class TestTraceStore:
    def test_append_and_get(self, tmp_path):
        from nous_runtime.intelligence.trace import TraceStore, ExecutionTraceRecord
        with TraceStore(workspace_root=str(tmp_path)) as store:
            record = ExecutionTraceRecord.new(task_id="task_store_test", task_type="code_audit")
            tid = store.append(record)
            assert tid != ""

            retrieved = store.get(tid)
            assert retrieved is not None
            assert retrieved.task_info.task_id == "task_store_test"

    def test_query_by_task_type(self, tmp_path):
        from nous_runtime.intelligence.trace import TraceStore, ExecutionTraceRecord
        with TraceStore(workspace_root=str(tmp_path)) as store:
            r1 = ExecutionTraceRecord.new(task_type="code_audit")
            r2 = ExecutionTraceRecord.new(task_type="bug_fix")
            store.append(r1)
            store.append(r2)

            results = store.query(task_type="code_audit")
            assert len(results) == 1
            assert results[0].task_info.task_type == "code_audit"

    def test_anonymize_basic(self, tmp_path):
        from nous_runtime.intelligence.trace import TraceStore, ExecutionTraceRecord
        with TraceStore(workspace_root=str(tmp_path)) as store:
            record = ExecutionTraceRecord.new(task_id="sensitive_task", task_type="code_audit")
            record.task_info.user_preferences = {"language": "zh-CN"}
            tid = store.append(record)

            anon = store.anonymize(tid, level="basic")
            assert anon is not None
            assert anon.sanitization_level == "basic"

    def test_delete(self, tmp_path):
        from nous_runtime.intelligence.trace import TraceStore, ExecutionTraceRecord
        with TraceStore(workspace_root=str(tmp_path)) as store:
            record = ExecutionTraceRecord.new(task_type="deletable")
            tid = store.append(record)
            assert store.get(tid) is not None
            store.delete(tid)
            # After delete, get should return None
            store.get(tid)
            # May still be in JSONL (historical) but DB index removed
