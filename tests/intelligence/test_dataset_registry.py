# -*- coding: utf-8 -*-
"""Tests for Dataset Registry."""



class TestDatasetRecord:
    def test_create_and_seal(self):
        from nous_runtime.intelligence.dataset import DatasetRecord, DatasetType
        record = DatasetRecord(
            dataset_id="ds_test_001",
            dataset_type=DatasetType.BENCHMARK,
            source="trace_store",
            task_count=100,
            privacy_level="internal",
            license="Apache-2.0",
            creation_method="trace_query",
        )
        record.seal()
        assert record.data_hash != ""
        assert record.created_at != ""

    def test_to_dict_and_from_dict(self):
        from nous_runtime.intelligence.dataset import DatasetRecord, DatasetType
        original = DatasetRecord(
            dataset_id="ds_test_002",
            dataset_type=DatasetType.EXPERIMENTAL,
            task_count=50,
            time_range=("2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z"),
            known_biases=["sampling_bias"],
            limitations=["small_sample"],
            trace_ids=["trace_1", "trace_2"],
        )
        original.seal()
        data = original.to_dict()
        restored = DatasetRecord.from_dict(data)
        assert restored.dataset_id == original.dataset_id
        assert restored.dataset_type == original.dataset_type
        assert restored.task_count == 50
        assert restored.known_biases == ["sampling_bias"]
        assert restored.trace_ids == ["trace_1", "trace_2"]


class TestDatasetRegistry:
    def test_register_and_get(self, tmp_path):
        from nous_runtime.intelligence.dataset import DatasetRegistry, DatasetRecord, DatasetType
        registry = DatasetRegistry(storage_dir=str(tmp_path))
        record = DatasetRecord(
            dataset_id="ds_reg_001",
            dataset_type=DatasetType.PRODUCTION,
            task_count=200,
        )
        ds_id = registry.register(record)
        assert ds_id == "ds_reg_001"

        retrieved = registry.get(ds_id)
        assert retrieved is not None
        assert retrieved.task_count == 200

    def test_query_by_type(self, tmp_path):
        from nous_runtime.intelligence.dataset import DatasetRegistry, DatasetRecord, DatasetType
        registry = DatasetRegistry(storage_dir=str(tmp_path))
        registry.register(DatasetRecord(dataset_id="ds_a", dataset_type=DatasetType.PRODUCTION, task_count=10))
        registry.register(DatasetRecord(dataset_id="ds_b", dataset_type=DatasetType.BENCHMARK, task_count=20))

        prod = registry.query(dataset_type=DatasetType.PRODUCTION)
        assert len(prod) == 1
        assert prod[0].dataset_id == "ds_a"

    def test_delete(self, tmp_path):
        from nous_runtime.intelligence.dataset import DatasetRegistry, DatasetRecord
        registry = DatasetRegistry(storage_dir=str(tmp_path))
        registry.register(DatasetRecord(dataset_id="to_delete", task_count=0))
        assert registry.get("to_delete") is not None
        assert registry.delete("to_delete") is True
        assert registry.get("to_delete") is None

    def test_count(self, tmp_path):
        from nous_runtime.intelligence.dataset import DatasetRegistry, DatasetRecord
        registry = DatasetRegistry(storage_dir=str(tmp_path))
        assert registry.count() == 0
        registry.register(DatasetRecord(dataset_id="ds1", task_count=1))
        registry.register(DatasetRecord(dataset_id="ds2", task_count=2))
        assert registry.count() == 2
