# -*- coding: utf-8 -*-
"""Shared fixtures for connectivity tests."""

import os
import socket
import sys
import time

import pytest

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def test_db_path(tmp_path):
    """Override database path for test isolation."""
    import remote_terminal.nous_core.config as _config
    test_dir = str(tmp_path / "nous_data")
    os.makedirs(test_dir, exist_ok=True)
    # Patch the data_dir
    if hasattr(_config, '_DATA_DIR'):
        _config._DATA_DIR = test_dir
    yield test_dir


@pytest.fixture
def control_plane():
    """Start a test Control Plane on a random port."""
    from nous_runtime.connectivity.control_plane.gateway import ControlPlaneGateway

    # Ask Windows for an available ephemeral port instead of sampling a fixed
    # range that may be occupied by long-running desktop services.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cp = ControlPlaneGateway(host="127.0.0.1", port=port)
    cp.start()
    time.sleep(0.3)  # Wait for server to start
    yield cp
    cp.stop()
    time.sleep(0.1)


@pytest.fixture
def paired_node(control_plane):
    """Create a paired node connected to the test Control Plane."""
    from nous_runtime.connectivity.node.daemon import NodeDaemon
    from nous_runtime.connectivity.protocol.identity import NodeIdentity
    import platform
    import secrets

    # Create pairing code on server
    code = control_plane.pairing.create_code()

    # Create node identity
    pk = secrets.token_hex(32)
    identity = NodeIdentity.create(
        node_name="test-node",
        node_role="personal_node",
        platform_os=platform.system(),
        platform_os_version=platform.release(),
        platform_arch=platform.machine(),
        platform_hostname=platform.node(),
        public_key=pk,
        capabilities=["system.echo"],
    )

    # Pair and connect
    node = NodeDaemon(
        control_plane_host=control_plane.host,
        control_plane_port=control_plane.port,
        node_name="test-node",
    )
    success = node.pair(code, identity)
    assert success, "Pairing failed"
    node.start()
    time.sleep(0.5)  # Wait for connection
    assert node.is_connected(), "Node failed to connect"

    yield node, control_plane

    node.stop()
    time.sleep(0.1)
