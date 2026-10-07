"""Opt-in Ray resource diagnostic; never a production ExecutionProvider.

The ordinary OCI provider remains PID64. A trusted operator must explicitly
acknowledge a temporary exception, select a digest-pinned local diagnostic image
and bound this profile into the existing governed Operation. No host fallback,
network, credentials, privileged execution or implicit Ray retries are available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from nous_runtime.environments.models import EnvironmentCommand, ExecutionEnvironment
from nous_runtime.environments.providers import (
    OCIContainerProvider,
    ProviderExecutionResult,
)

SOURCE_IMAGE = "rayproject/ray@sha256:de04957cc0a2f30563389ab945b5f96358f601ae76bd49755f5727adbcb5e7ba"
IMAGE_RECIPE = (
    f"FROM {SOURCE_IMAGE}\nUSER root\nRUN chmod o+rx /home/ray\nUSER 65532:65532\n"
)
PYTHON = "/home/ray/anaconda3/bin/python"


@dataclass(frozen=True)
class RayDiagnosticProfile:
    """Host-owned diagnostic scope, not a Work-supplied resource permission."""

    image: str
    pids: int = 64
    exception_acknowledged: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise ValueError("A local immutable diagnostic image digest is required")
        if type(self.pids) is not int or not 64 <= self.pids <= 256:
            raise ValueError("Diagnostic PID bound must be an integer between64 and256")
        if self.pids > 64 and self.exception_acknowledged is not True:
            raise PermissionError("Explicit temporary diagnostic exception required")

    def to_dict(self):
        return {
            "schema": "apeir.ray-diagnostic-profile/v1",
            "diagnostic_only": True,
            "image": self.image,
            "source_image": SOURCE_IMAGE,
            "recipe_digest": hashlib.sha256(IMAGE_RECIPE.encode()).hexdigest(),
            "pids": self.pids,
            "cpu_limit": 1.0,
            "memory_limit_mb": 2048,
            "temporary_filesystem_mb": 512,
            "timeout_seconds": 45,
            "network": "none",
            "uid": 65532,
            "ray_retries": 0,
        }


# Guest telemetry contains executable names/counts, never command arguments or
# environment values. Persist each sample so forced cleanup retains evidence.
GUEST = """import collections,json,pathlib,threading,time
import ray
phase='startup';samples=[];done=threading.Event()
mode=json.loads(pathlib.Path('/model-workspace/mode.json').read_text())
def sample():
 while not done.is_set():
  try:
   cg=pathlib.Path('/sys/fs/cgroup');names=collections.Counter();processes=threads=rss=0
   for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
     v={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (p/'status').read_text().splitlines() if ':' in line}
     names[v['Name']]+=1;processes+=1;threads+=int(v['Threads']);rss+=int(v.get('VmRSS','0 kB').split()[0])*1024
    except (OSError,KeyError,ValueError):pass
   cpu=dict(line.split() for line in (cg/'cpu.stat').read_text().splitlines())
   samples.append({'t':round(time.monotonic(),3),'phase':phase,'processes':processes,'threads':threads,'names':dict(names),'pids_current':int((cg/'pids.current').read_text()),'pids_peak':int((cg/'pids.peak').read_text()) if (cg/'pids.peak').exists() else None,'memory_current':int((cg/'memory.current').read_text()),'memory_peak':int((cg/'memory.peak').read_text()),'rss_bytes':rss,'cpu_usage_usec':int(cpu['usage_usec'])})
   pathlib.Path('/model-workspace/samples.tmp').write_text(json.dumps(samples));pathlib.Path('/model-workspace/samples.tmp').replace('/model-workspace/samples.json')
  except OSError:pass
  done.wait(.2)
monitor=threading.Thread(target=sample,daemon=True);monitor.start()
print(json.dumps({'version':ray.__version__,'pid_limit':pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip()}),flush=True)
try:
 ray.init(num_cpus=1,include_dashboard=False,object_store_memory=80*1024*1024,_node_ip_address='127.0.0.1',_temp_dir='/model-workspace/ray-state',_system_config={'num_server_call_thread':1,'gcs_server_rpc_server_thread_num':1,'gcs_server_rpc_client_thread_num':1,'object_manager_rpc_threads_num':1,'worker_num_grpc_internal_threads':1})
 phase='steady'
 @ray.remote(max_retries=0,retry_exceptions=False)
 def once(mode):
  import pathlib,ray,time,json
  p=pathlib.Path('/model-workspace/count.txt');p.write_text(str(int(p.read_text())+1) if p.exists() else '1')
  evidence={'task_id':str(ray.get_runtime_context().get_task_id()),'worker_id':str(ray.get_runtime_context().get_worker_id()),'node_id':str(ray.get_runtime_context().get_node_id()),'effect_count':p.read_text()}
  pathlib.Path('/model-workspace/task-evidence.json').write_text(json.dumps(evidence))
  if mode=='failure':raise RuntimeError('deterministic fake diagnostic failure after effect')
  time.sleep(300 if mode=='cancel' else 2)
  return evidence
 print(json.dumps({'task':ray.get(once.remote(mode),timeout=15)}),flush=True)
 time.sleep(3)
finally:
 phase='shutdown';start=time.monotonic();ray.shutdown();print(json.dumps({'shutdown_seconds':round(time.monotonic()-start,3)}),flush=True)
 time.sleep(2);done.set();monitor.join(1)
"""


# Preserve host access only to fake diagnostic files owned by the guest. Never
# follow symlinks or touch any path outside the single mounted Ray-state tree.
RESTORE_FAKE_EVIDENCE = """import os,pathlib
root=pathlib.Path('/model-workspace/ray-state')
if root.is_dir() and not root.is_symlink():
 for base,dirs,files in os.walk(root,followlinks=False):
  for name in files:
   path=pathlib.Path(base)/name
   if not path.is_symlink():
    try:path.chmod(0o644)
    except FileNotFoundError:pass
  path=pathlib.Path(base)
  if not path.is_symlink():path.chmod(0o777)
import json
cg=pathlib.Path('/sys/fs/cgroup')
print(json.dumps({name:int((cg/name).read_text()) for name in ('pids.current','pids.peak','memory.current','memory.peak')}))
"""


def summarize_samples(samples):
    """cgroup accounting is authoritative; RSS sums may double-count mappings."""
    summary = {}
    for phase in ("startup", "steady", "shutdown"):
        rows = [s for s in samples if s["phase"] == phase]
        if not rows:
            continue
        elapsed = rows[-1]["t"] - rows[0]["t"]
        summary[phase] = {
            "samples": len(rows),
            "seconds": round(elapsed, 3),
            "cpu_mean_cores": round(
                (rows[-1]["cpu_usage_usec"] - rows[0]["cpu_usage_usec"])
                / 1_000_000
                / elapsed,
                3,
            )
            if elapsed > 0
            else None,
            "peaks": {
                k: max(s[k] or 0 for s in rows)
                for k in (
                    "processes",
                    "threads",
                    "pids_current",
                    "pids_peak",
                    "memory_current",
                    "memory_peak",
                )
            },
            "cpu_peak_sample_cores": round(
                max(
                    (
                        (b["cpu_usage_usec"] - a["cpu_usage_usec"])
                        / 1_000_000
                        / (b["t"] - a["t"])
                        for a, b in zip(rows, rows[1:])
                        if b["t"] > a["t"]
                    ),
                    default=0.0,
                ),
                3,
            ),
            "peak_topology": max(rows, key=lambda s: s["pids_current"])["names"],
            "last": rows[-1],
        }
    return summary


class RayBoundedDiagnostic:
    """One owned OCI environment per diagnostic, always destroyed, no retries."""

    def __init__(self, root: Path, profile: RayDiagnosticProfile):
        self.root = root.resolve()
        self.profile = profile
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o755)
        self.workspace.chmod(0o777)
        self._host_pids = {}
        self._mode = "execute"
        self._cancel = threading.Event()
        self.report = {}
        self._used = False
        self.provider = OCIContainerProvider(runner=self._runner)
        self.environment = ExecutionEnvironment.from_mapping(
            {
                "provider": "oci",
                "environment_type": "oci_container",
                "image": profile.image,
                "memory_limit_mb": 2048,
                "filesystem_policy": {"temporary_filesystem_mb": 512},
                "workspace_mounts": [
                    {
                        "source": "workspace",
                        "target": "/model-workspace",
                        "mode": "read-write",
                    }
                ],
            },
            new_identity=True,
        )
        self.handle = ""

    def _docker(self, argv, timeout=30):
        environment = dict(os.environ)
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(key, None)
        return subprocess.run(
            [self.provider._engine, "--host=unix:///var/run/docker.sock", *argv],
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def _runner(self, argv, cwd, timeout, output, extra):
        argv = list(argv)
        assert argv[0] == self.provider._engine
        if argv[1] == "create":
            assert argv[argv.index("--pids-limit") + 1] == "64"
            argv[argv.index("--pids-limit") + 1] = str(self.profile.pids)
        if argv[1] != "exec":
            r = self._docker(argv[1:], timeout)
            return ProviderExecutionResult(
                r.returncode == 0,
                r.returncode,
                stdout=r.stdout[:output],
                stderr=r.stderr[:output],
            )
        # Poll the owned diagnostic only, never enumerate unrelated host processes.
        result = []
        errors = []

        def execute():
            try:
                result.append(self._docker(argv[1:], timeout))
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=execute, daemon=True)
        worker.start()
        start = time.monotonic()
        while worker.is_alive() and time.monotonic() - start < timeout:
            r = self._docker(["top", self.handle, "-eo", "pid,comm"])
            if r.returncode == 0:
                for line in r.stdout.splitlines()[1:]:
                    pid = line.split()[0]
                    try:
                        self._host_pids[pid] = (
                            Path("/proc", pid, "stat").read_text().split()[21]
                        )
                    except (OSError, IndexError):
                        pass
            if self._cancel.is_set() or (
                self._mode == "cancel"
                and (self.workspace / "task-evidence.json").exists()
            ):
                self._cancel.set()
                self._restore_fake_evidence()
                cancel_start = time.monotonic()
                self.provider.destroy(self.environment, self.handle)
                self.report["cancel_destroy_seconds"] = round(
                    time.monotonic() - cancel_start, 3
                )
                break
            time.sleep(0.2)
        worker.join(1)
        if errors and not isinstance(errors[0], subprocess.TimeoutExpired):
            raise errors[0]
        timed_out = bool(errors) or worker.is_alive()
        if not result:
            return ProviderExecutionResult(
                False, -1, timed_out=timed_out, stderr="bounded diagnostic interrupted"
            )
        r = result[0]
        return ProviderExecutionResult(
            r.returncode == 0 and not self._cancel.is_set(),
            r.returncode if not self._cancel.is_set() else -1,
            stdout=r.stdout[:output],
            stderr=r.stderr[:output],
            timed_out=timed_out,
        )

    def _restore_fake_evidence(self):
        # Exact owned handle, same container UID and unchanged containment. This
        # is artifact housekeeping, never another Ray Task or side-effect retry.
        if self._docker(["inspect", self.handle]).returncode != 0:
            return
        result = self._docker(
            ["exec", self.handle, PYTHON, "-c", RESTORE_FAKE_EVIDENCE], timeout=5
        )
        if result.returncode:
            raise RuntimeError("Guest-owned diagnostic evidence cleanup failed")
        self.report["final_cgroup"] = json.loads(result.stdout)

    def cancel(self):
        self._cancel.set()

    def _assert_default(self):
        argv = OCIContainerProvider(
            engine_path=self.provider._engine
        ).build_create_command(self.environment, self.root)
        assert argv[argv.index("--pids-limit") + 1] == "64"

    def run(self, mode="execute", *, expected_profile=None):
        if self._used or any(
            (self.workspace / name).exists()
            for name in ("count.txt", "probe.py", "mode.json", "ray-state")
        ):
            raise PermissionError(
                "A diagnostic environment cannot replay an uncertain effect"
            )
        if mode not in {"execute", "failure", "cancel"}:
            raise ValueError("Unsupported diagnostic mode")
        if expected_profile is not None and self.profile.to_dict() != expected_profile:
            raise PermissionError(
                "Profile differs from original governed resource binding"
            )
        self._assert_default()
        self._used = True
        self._mode = mode
        (self.workspace / "probe.py").write_text(GUEST)
        (self.workspace / "mode.json").write_text(json.dumps(mode))
        (self.workspace / "probe.py").chmod(0o644)
        (self.workspace / "mode.json").chmod(0o644)
        self.report = {"profile": self.profile.to_dict(), "mode": mode}
        self.handle = f"nous-{self.environment.environment_id[-12:]}"
        try:
            prepared = self.provider.prepare(self.environment, self.root)
            if prepared != self.handle:
                raise RuntimeError("Diagnostic container identity differs")
            self.provider.start(self.environment, self.handle)
            inspected = json.loads(self._docker(["inspect", self.handle]).stdout)[0]
            self.report["limits"] = {
                k: inspected["HostConfig"][k]
                for k in (
                    "PidsLimit",
                    "Memory",
                    "NanoCpus",
                    "ReadonlyRootfs",
                    "NetworkMode",
                    "CapDrop",
                    "SecurityOpt",
                    "Privileged",
                    "PidMode",
                )
            }
            self.report["uid"] = inspected["Config"]["User"]
            result = self.provider.execute(
                self.environment,
                self.handle,
                EnvironmentCommand(
                    argv=(PYTHON, "/model-workspace/probe.py"),
                    timeout_seconds=45,
                    env={
                        "HOME": "/tmp",
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                        "NO_PROXY": "127.0.0.1,localhost",
                        "RAY_USAGE_STATS_ENABLED": "0",
                        "RAY_num_server_call_thread": "1",
                        "RAY_gcs_server_rpc_server_thread_num": "1",
                        "RAY_gcs_server_rpc_client_thread_num": "1",
                        "RAY_object_manager_rpc_threads_num": "1",
                        "RAY_worker_num_grpc_internal_threads": "1",
                    },
                ),
            )
            self.report["result"] = result.to_dict()
            return result
        finally:
            started = time.monotonic()
            try:
                self._restore_fake_evidence()
            finally:
                self.provider.destroy(self.environment, self.handle)
            remaining = []
            for pid, identity in self._host_pids.items():
                try:
                    if Path("/proc", pid, "stat").read_text().split()[21] == identity:
                        remaining.append(pid)
                except (OSError, IndexError):
                    pass
            self._assert_default()
            self.report["cleanup"] = {
                "seconds": round(time.monotonic() - started, 3),
                "tracked_host_processes": len(self._host_pids),
                "remaining_host_processes": remaining,
                "container_absent": self._docker(["inspect", self.handle]).returncode
                != 0,
                "default_pids_after": 64,
            }
            samples = self.workspace / "samples.json"
            if samples.exists():
                self.report["measurements"] = summarize_samples(
                    json.loads(samples.read_text())
                )
            (self.root / "report.json").write_text(json.dumps(self.report, indent=2))
            if remaining or not self.report["cleanup"]["container_absent"]:
                raise RuntimeError("Owned diagnostic cleanup failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        required=True,
        help="local immutable image ID built from the pinned recipe",
    )
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--pids", type=int, default=64)
    parser.add_argument("--acknowledge-diagnostic-exception", action="store_true")
    parser.add_argument(
        "--mode", choices=("execute", "failure", "cancel"), default="execute"
    )
    args = parser.parse_args()
    if args.workspace.exists():
        parser.error(
            "Use a new diagnostic workspace; never replay a prior diagnostic effect"
        )
    profile = RayDiagnosticProfile(
        args.image, args.pids, args.acknowledge_diagnostic_exception
    )
    diagnostic = RayBoundedDiagnostic(args.workspace, profile)
    result = diagnostic.run(args.mode)
    print(json.dumps(diagnostic.report, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
