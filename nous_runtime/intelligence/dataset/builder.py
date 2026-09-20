# -*- coding: utf-8 -*-
"""DatasetBuilder — creates datasets from trace stores."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from .models import DatasetRecord, DatasetType
from .registry import DatasetRegistry

_log = logging.getLogger("nous.dataset.builder")


class DatasetBuilder:
    """Builds versioned datasets from trace stores.

    Supports: filtering, anonymization, train/val/test splitting.
    """

    def __init__(self, registry: DatasetRegistry | None = None) -> None:
        self.registry = registry or DatasetRegistry()

    def build_from_traces(
        self,
        trace_store: Any,          # TraceStore instance
        *,
        dataset_type: DatasetType = DatasetType.EXPERIMENTAL,
        privacy_level: str = "internal",
        task_type_filter: str = "",
        status_filter: str = "",
        session_filter: str = "",
        max_tasks: int = 10000,
        anonymization: str = "basic",
        description: str = "",
        license_str: str = "Apache-2.0",
    ) -> DatasetRecord:
        """Build a dataset by querying a TraceStore."""
        # Query traces
        traces = trace_store.query(
            task_type=task_type_filter,
            status=status_filter,
            session_id=session_filter,
            limit=max_tasks,
        )

        # Anonymize if needed
        if anonymization != "none":
            traces = [
                trace_store.anonymize(t.trace_id, level=anonymization) or t
                for t in traces
            ]
            traces = [t for t in traces if t is not None]

        # Generate dataset ID
        ds_id = f"ds_{dataset_type.value}_{uuid.uuid4().hex[:8]}"

        # Determine time range
        timestamps = [t.created_at for t in traces if t.created_at]
        time_range = (
            (min(timestamps), max(timestamps)) if timestamps else ("", "")
        )

        # Export traces to dataset storage
        storage_dir = Path(self.registry._dir) / ds_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / "data.jsonl"

        with open(storage_path, "w", encoding="utf-8") as f:
            for t in traces:
                f.write(t.to_jsonl() + "\n")

        # Create record
        record = DatasetRecord(
            dataset_id=ds_id,
            dataset_type=dataset_type,
            source="trace_store",
            time_range=time_range,
            task_count=len(traces),
            privacy_level=privacy_level,
            license=license_str,
            creation_method="trace_query",
            storage_path=str(storage_path),
            storage_format="jsonl",
            trace_ids=[t.trace_id for t in traces],
            description=description or f"Dataset built from {len(traces)} traces",
            metadata={
                "anonymization_level": anonymization,
                "task_type_filter": task_type_filter,
                "status_filter": status_filter,
            },
        )

        # Register
        self.registry.register(record)
        return record

    def split(
        self,
        dataset_id: str,
        ratios: tuple[float, float, float] = (0.7, 0.15, 0.15),
        random_seed: int = 42,
    ) -> dict[str, DatasetRecord]:
        """Split a dataset into train/val/test subsets.

        Returns dict with keys "train", "val", "test".
        """
        import random as _random

        parent = self.registry.get(dataset_id)
        if parent is None:
            raise ValueError(f"Dataset not found: {dataset_id}")

        if parent.storage_format != "jsonl" or not parent.storage_path:
            raise ValueError("Can only split JSONL datasets with valid storage_path")

        # Read all trace dicts
        data_path = Path(parent.storage_path)
        records = []
        for line in data_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))

        # Shuffle with fixed seed
        rng = _random.Random(random_seed)
        rng.shuffle(records)

        # Split
        n = len(records)
        train_n = int(n * ratios[0])
        val_n = int(n * ratios[1])

        splits = {
            "train": records[:train_n],
            "val": records[train_n:train_n + val_n],
            "test": records[train_n + val_n:],
        }

        results = {}
        for split_name, split_records in splits.items():
            split_id = f"{dataset_id}_{split_name}"
            split_dir = Path(self.registry._dir) / split_id
            split_dir.mkdir(parents=True, exist_ok=True)
            split_path = split_dir / "data.jsonl"

            with open(split_path, "w", encoding="utf-8") as f:
                for r in split_records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            split_record = DatasetRecord(
                dataset_id=split_id,
                version=parent.version,
                dataset_type=parent.dataset_type,
                source=parent.source,
                time_range=parent.time_range,
                task_count=len(split_records),
                privacy_level=parent.privacy_level,
                license=parent.license,
                creation_method="split",
                storage_path=str(split_path),
                storage_format="jsonl",
                trace_ids=[r.get("trace_id", "") for r in split_records],
                description=f"{split_name} split of {dataset_id}",
                metadata={"parent_dataset": dataset_id, "split": split_name, "random_seed": random_seed},
            )
            split_record.seal()
            self.registry.register(split_record)
            results[split_name] = split_record

        return results
