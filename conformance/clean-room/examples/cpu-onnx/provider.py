"""
Clean-Room Test 2: CPU/ONNX Execution Provider

Uses ONLY public Provider SDK. Discovers local CPU, loads ONNX model, runs inference.
Zero kernel imports — grep for 'kernel/' must return nothing.
"""

import os
import time
import platform
from typing import Optional
from nous_provider import (
    DiscoveryProvider,
    ResourceProvider,
    ExecutionProvider,
    TelemetryProvider,
    ProviderPackage,
    register_provider,
    Device,
    DeviceSpec,
    DeviceStatus,
    DevicePhase,
    DeviceType,
    DeviceClass,
    ResourceVector,
    ResourceClaim,
    ResourceLease,
)


class CPUOnnxProvider(
    DiscoveryProvider, ResourceProvider, ExecutionProvider, TelemetryProvider
):
    def __init__(self):
        self._cpu_id = f"dev-cpu-{platform.node()}"
        self._model_loaded = {}
        self._start = time.time()
        cpu_count = os.cpu_count() or 1
        try:
            import psutil

            ram = psutil.virtual_memory().total
        except ImportError:
            ram = 8 * 1024**3
        self._total_ram = ram
        self._total_cores = cpu_count
        self._available = ResourceVector(
            cpu_cores_millis=cpu_count * 1000, ram_bytes=ram
        )

    def discover(self) -> list[Device]:
        return [
            Device(
                device_id=self._cpu_id,
                spec=DeviceSpec(
                    device_type=DeviceType.CPU,
                    vendor=platform.processor() or "unknown",
                    model=platform.machine(),
                    architecture=platform.machine(),
                    total_resources=self._available,
                    capabilities=("inference", "embedding"),
                    supported_engines=("onnx",),
                    supported_dtypes=("fp32", "fp16", "int8"),
                    compute_units=self._total_cores,
                ),
                status=DeviceStatus(phase=DevicePhase.READY, available=self._available),
                device_class=DeviceClass(
                    vendor="cpu", runtime="general", tier="general"
                ),
            )
        ]

    def probe(self, device_id: str) -> Optional[Device]:
        if device_id != self._cpu_id:
            return None
        d = self.discover()[0]
        d.status.last_health_check = time.time()
        return d

    def claim(self, claim: ResourceClaim) -> bool:
        return claim.minimum.fits_within(self._available)

    def reserve(
        self, device_id: str, amount: ResourceVector
    ) -> Optional[ResourceLease]:
        if not amount.fits_within(self._available):
            return None
        self._available = self._available - amount
        return ResourceLease(
            workload_id="cpu-onnx-wl",
            device_id=device_id,
            reserved=amount,
            granted_at_us=int(time.time() * 1e6),
            expires_at_us=int(time.time() * 1e6) + 300_000_000,
        )

    def release(self, lease_id: str) -> bool:
        return True

    def load(self, model_id: str, device_id: str, config: dict) -> bool:
        path = config.get("model_path", "")
        if not os.path.isfile(path):
            return False
        import onnxruntime as ort

        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self._model_loaded[model_id] = sess
        return True

    def infer(self, request: dict) -> dict:
        model_id = request.get("model_id", "")
        sess = self._model_loaded.get(model_id)
        if not sess:
            return {"error": "Model not loaded"}
        input_name = sess.get_inputs()[0].name
        input_data = request.get("input_data", [[0.0]])
        import numpy as np

        result = sess.run(None, {input_name: np.array(input_data, dtype=np.float32)})
        return {"output": result[0].tolist(), "model": model_id}

    def unload(self, model_id: str) -> bool:
        self._model_loaded.pop(model_id, None)
        return True

    def metrics(self, device_id: str) -> dict:
        return {
            "device_id": device_id,
            "healthy": True,
            "uptime_seconds": time.time() - self._start,
            "models_loaded": len(self._model_loaded),
            "ram_available_bytes": self._available.ram_bytes,
        }


if __name__ == "__main__":
    pkg = ProviderPackage(
        name="clean-room-cpu-onnx",
        version="1.0.0-rc7",
        provider_class="device",
        discovery=CPUOnnxProvider(),
        resource=CPUOnnxProvider(),
        execution=CPUOnnxProvider(),
        telemetry=CPUOnnxProvider(),
        capabilities=["inference", "onnx"],
        permissions=["filesystem:read"],
        conformance_level="RUNNABLE",
    )
    ok = register_provider(pkg)
    print("✅" if ok else "❌", "CPU/ONNX Provider registered")
