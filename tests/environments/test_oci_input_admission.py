"""Untrusted image references cannot become container-engine options."""

from dataclasses import replace
import json

import pytest

from nous_runtime.environments import (
    EnvironmentProviderRegistry,
    EnvironmentRuntime,
    EnvironmentValidationError,
    ExecutionEnvironment,
    OCIContainerProvider,
    ProviderExecutionResult,
)


def _spec(image):
    return {"provider": "oci", "environment_type": "oci_container", "image": image}


@pytest.mark.parametrize(
    "image",
    [
        "--privileged=true",
        "--privileged=1",
        "--network",
        "--network=host",
        "--pid=host",
        "--user=root",
        "--entrypoint=/bin/sh",
        "--volume=/var/run/docker.sock:/socket",
        "-v",
        "-it",
        "--",
        "  --privileged=true  ",
    ],
)
def test_option_like_images_fail_before_persistence_or_engine_call(tmp_path, image):
    calls = []
    provider = OCIContainerProvider(
        engine_path="docker", runner=lambda *args: calls.append(args)
    )
    runtime = EnvironmentRuntime(
        tmp_path, providers=EnvironmentProviderRegistry({"oci": provider})
    )
    with pytest.raises(EnvironmentValidationError, match="command-line option"):
        runtime.create(_spec(image))
    assert not calls
    assert not list(runtime.storage.glob("env_*.json"))

    valid = ExecutionEnvironment.from_mapping(
        _spec("python:3.12-slim"), new_identity=True
    )
    with pytest.raises(EnvironmentValidationError, match="command-line option"):
        provider.prepare(replace(valid, image=image), tmp_path)
    assert not calls


def test_restart_rejects_option_image_even_with_matching_record_digest(tmp_path):
    calls = []
    provider = OCIContainerProvider(
        engine_path="docker", runner=lambda *args: calls.append(args)
    )
    registry = EnvironmentProviderRegistry({"oci": provider})
    runtime = EnvironmentRuntime(tmp_path, providers=registry)
    record = runtime.create(_spec("python:3.12-slim"))
    environment = ExecutionEnvironment.from_mapping(
        {
            key: value
            for key, value in record.items()
            if key not in {"sha256", "artifact_id", "operation_run_id", "compatibility"}
        }
    )
    invalid = replace(environment, image="--privileged=true")
    runtime._environment_path(environment.environment_id).write_text(
        json.dumps({**invalid.to_dict(), "sha256": invalid.digest()})
    )
    reopened = EnvironmentRuntime(tmp_path, providers=registry)
    with pytest.raises(EnvironmentValidationError, match="command-line option"):
        reopened.start(environment.environment_id)
    assert not calls


@pytest.mark.parametrize("engine", ["docker", "podman"])
@pytest.mark.parametrize(
    "image",
    [
        "python",
        "python:3.12-slim",
        "localhost:5000/team/python:3.12-slim",
        "registry.example/team/python@sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
    ],
)
def test_canonical_images_remain_positional_after_engine_option_boundary(
    tmp_path, engine, image
):
    calls = []

    def runner(argv, *args):
        calls.append(argv)
        return ProviderExecutionResult(True, 0)

    provider = OCIContainerProvider(engine_path=engine, runner=runner)
    environment = ExecutionEnvironment.from_mapping(_spec(image), new_identity=True)
    assert provider.prepare(environment, tmp_path) == (
        "nous-" + environment.environment_id[-12:]
    )
    assert len(calls) == 1
    argv = calls[0]
    boundary = argv.index("--")
    assert argv[boundary + 1 :] == [
        image,
        "/bin/sh",
        "-c",
        "trap 'exit 0' TERM INT; while :; do sleep 3600; done",
    ]
    assert argv[:2] == [engine, "create"]
    assert argv[argv.index("--pids-limit") + 1] == "64"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--memory") + 1] == "512m"
    assert argv[argv.index("--cpus") + 1] == "1.0"
    assert "--read-only" in argv[:boundary]
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert "--volume" not in argv
