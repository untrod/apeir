# -*- coding: utf-8 -*-
"""
Process-boundary connectivity test using real TCP socket + SQLite.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_CP_RUNNER = r"""
import sys, os, json, time
sys.path.insert(0, r'{cwd}')
os.environ['NOUS_DATA_DIR'] = r'{data_dir}'
port = {port}

from nous_runtime.connectivity.control_plane.gateway import ControlPlaneGateway

cp = ControlPlaneGateway(host='127.0.0.1', port=port)
cp.start()
time.sleep(0.5)
# Signal ready
print(json.dumps({{"event": "ready", "port": port}}), flush=True)

# Main loop: wait for commands from stdin
while True:
    line = sys.stdin.readline()
    if not line:
        break
    cmd = json.loads(line)
    action = cmd.get("action")

    if action == "create_pairing_code":
        code = cp.pairing.create_code()
        print(json.dumps({{"event": "pairing_code", "code": code}}), flush=True)

    elif action == "submit_task":
        task = cp.submit_task(cmd.get("capability", "system.echo"),
                              cmd.get("params", {{}}))
        if task:
            print(json.dumps({{"event": "task_submitted", "task_id": task["task_id"]}}), flush=True)

    elif action == "check_task":
        tid = cmd.get("task_id", "")
        t = cp.task_coordinator.get(tid) if tid else None
        if t:
            print(json.dumps({{"event": "task_state", "task": t}}), flush=True)
        else:
            # Check for any completed task
            completed = cp.task_coordinator.list_all("completed")
            if completed:
                print(json.dumps({{"event": "task_state", "task": completed[0]}}), flush=True)
            else:
                print(json.dumps({{"event": "task_state", "task": None}}), flush=True)

    elif action == "status":
        print(json.dumps({{"event": "status", "status": cp.get_status()}}), flush=True)

    elif action == "stop":
        break

cp.stop()
"""

_NODE_RUNNER = r"""
import sys, os, json, time
sys.path.insert(0, r'{cwd}')
os.environ['NOUS_DATA_DIR'] = r'{data_dir}'

from nous_runtime.connectivity.node.daemon import NodeDaemon
from nous_runtime.connectivity.protocol.identity import NodeIdentity
import platform, secrets

node = None
identity = None

while True:
    line = sys.stdin.readline()
    if not line:
        break
    cmd = json.loads(line)
    action = cmd.get("action")

    if action == "create_identity":
        pk = secrets.token_hex(32)
        identity = NodeIdentity.create(
            node_name='proc-node', node_role='personal_node',
            platform_os=platform.system(), platform_os_version=platform.release(),
            platform_arch=platform.machine(), platform_hostname=platform.node(),
            public_key=pk, capabilities=cmd.get("capabilities", ['system.echo']),
        )
        print(json.dumps({{"event": "identity_created", "node_id": identity.node_id}}), flush=True)

    elif action == "pair":
        node = NodeDaemon(
            control_plane_host=cmd.get("host", "127.0.0.1"),
            control_plane_port=cmd.get("port", 9770),
            node_name='proc-node',
        )
        node.node_id = identity.node_id
        result = node.pair(cmd["code"], identity)
        print(json.dumps({{"event": "pair_result", "success": result}}), flush=True)

    elif action == "start":
        if node:
            node.start()
            time.sleep(1.0)
        print(json.dumps({{"event": "started", "connected": node.is_connected() if node else False}}), flush=True)

    elif action == "status":
        print(json.dumps({{"event": "node_status", "connected": node.is_connected() if node else False}}), flush=True)

    elif action == "stop":
        if node:
            node.stop()
        break

if node:
    node.stop()
"""


class TestProcessBoundary:
    """Process-boundary test: CP + Node communicate over real TCP, real SQLite."""

    def test_full_flow(self):
        port = _find_free_port()
        data_dir = tempfile.mkdtemp()

        # Start CP
        cp_proc = subprocess.Popen(
            [sys.executable, "-c", _CP_RUNNER.format(cwd=os.getcwd(), port=port, data_dir=data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        def cp_cmd(action, **kwargs):
            cmd = {"action": action, **kwargs}
            cp_proc.stdin.write(json.dumps(cmd) + "\n")
            cp_proc.stdin.flush()
            line = cp_proc.stdout.readline()
            return json.loads(line) if line else {}

        def read_cp_event():
            line = cp_proc.stdout.readline()
            return json.loads(line) if line else {}

        # Wait for CP ready
        evt = read_cp_event()
        assert evt.get("event") == "ready", f"Expected ready, got {evt}"

        # Get pairing code
        evt = cp_cmd("create_pairing_code")
        code = evt.get("code")
        assert code, f"No pairing code: {evt}"
        print(f"  Pairing code: {code}")

        # Start Node
        node_proc = subprocess.Popen(
            [sys.executable, "-c", _NODE_RUNNER.format(cwd=os.getcwd(), data_dir=data_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        def node_cmd(action, **kwargs):
            cmd = {"action": action, **kwargs}
            node_proc.stdin.write(json.dumps(cmd) + "\n")
            node_proc.stdin.flush()
            line = node_proc.stdout.readline()
            return json.loads(line) if line else {}

        # Create identity + pair
        evt = node_cmd("create_identity")
        assert evt.get("event") == "identity_created"
        print(f"  Node identity: {evt.get('node_id')}")

        evt = node_cmd("pair", code=code, host="127.0.0.1", port=port)
        assert evt.get("success"), f"Pair failed: {evt}"
        print("  Paired ✓")

        # Start node
        evt = node_cmd("start")
        assert evt.get("connected"), f"Not connected: {evt}"
        print("  Connected ✓")

        # Submit task
        time.sleep(0.5)
        evt = cp_cmd("submit_task", capability="system.echo", params={"message": "process-boundary-test"})
        task_id = evt.get("task_id")
        assert task_id, f"Task submission failed: {evt}"
        print(f"  Task: {task_id}")

        # Wait for completion
        for _ in range(20):  # 10 seconds
            time.sleep(0.5)
            evt = cp_cmd("check_task")
            task = evt.get("task")
            if task and task.get("state") == "completed":
                result = task.get("result", {})
                assert result.get("echo") == "process-boundary-test", f"Wrong result: {result}"
                print(f"  Result: {result}")
                break
        else:
            # Try one more time
            evt = cp_cmd("check_task")
            task = evt.get("task")
            assert task and task.get("state") == "completed", f"Task not completed: {task}"

        print("  Process boundary test passed ✓")

        # Cleanup
        cp_cmd("stop")
        node_cmd("stop")
        cp_proc.wait(timeout=5)
        node_proc.wait(timeout=5)
        for proc in (cp_proc, node_proc):
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()
