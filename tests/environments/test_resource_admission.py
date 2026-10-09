"""Resource limits fail closed before records, engine calls or subprocesses."""

from dataclasses import replace
import json

import pytest

from nous_runtime.environments import (
    EnvironmentCommand,
    EnvironmentProviderRegistry,
    EnvironmentRuntime,
    EnvironmentValidationError,
    ExecutionEnvironment,
    LocalSandboxProvider,
    OCIContainerProvider,
)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), "NaN", True, None, [], {}, 0, 65],
)
def test_cpu_admission_rejects_nonfinite_ambiguous_and_out_of_range(value, tmp_path):
    calls = []
    provider = OCIContainerProvider(
        engine_path="docker", runner=lambda *args: calls.append(args)
    )
    runtime = EnvironmentRuntime(
        tmp_path, providers=EnvironmentProviderRegistry({"oci": provider})
    )
    with pytest.raises(EnvironmentValidationError, match="cpu_limit"):
        runtime.create(
            {
                "provider": "oci",
                "environment_type": "oci_container",
                "image": "fake",
                "cpu_limit": value,
            }
        )
    assert not calls
    assert not list(runtime.storage.glob("env_*.json"))


@pytest.mark.parametrize(
    "field,valid",
    [
        ("memory_limit_mb", 256),
        ("memory_limit", 256),
        ("lifetime_seconds", 600),
        ("lifetime", 600),
        ("temporary_filesystem_mb", 64),
        ("timeout_seconds", 60),
        ("max_output_bytes", 1024),
    ],
)
@pytest.mark.parametrize(
    "invalid", [True, None, float("nan"), "private-test-value", "fraction"]
)
def test_integer_limits_never_truncate_or_coerce_ambiguous_values(
    field, valid, invalid
):
    def parse(value):
        if field == "temporary_filesystem_mb":
            return ExecutionEnvironment.from_mapping(
                {"filesystem_policy": {field: value}}, new_identity=True
            )
        if field in {"timeout_seconds", "max_output_bytes"}:
            return EnvironmentCommand.from_mapping({"argv": ["python"], field: value})
        return ExecutionEnvironment.from_mapping({field: value}, new_identity=True)

    parse(valid)
    if invalid == "fraction":
        invalid = valid + 0.5
    with pytest.raises(EnvironmentValidationError) as error:
        parse(invalid)
    assert "private-test-value" not in str(error.value)


@pytest.mark.parametrize("field", ["timeout_seconds", "max_output_bytes"])
def test_explicit_zero_does_not_select_default(field):
    with pytest.raises(EnvironmentValidationError, match=field):
        EnvironmentCommand.from_mapping({"argv": ["python"], field: 0})


def test_valid_limits_preserve_numeric_text_integral_floats_and_digest():
    environment = ExecutionEnvironment.from_mapping(
        {
            "cpu_limit": "1.5",
            "memory_limit": "256",
            "lifetime": 600.0,
            "filesystem_policy": {"temporary_filesystem_mb": 0},
        },
        new_identity=True,
    )
    assert (
        environment.cpu_limit,
        environment.memory_limit_mb,
        environment.lifetime_seconds,
    ) == (1.5, 256, 600)
    assert environment.filesystem_policy.temporary_filesystem_mb == 0
    assert (
        ExecutionEnvironment.from_mapping(environment.to_dict()).digest()
        == environment.digest()
    )
    command = EnvironmentCommand.from_mapping(
        {"argv": ["python"], "timeout_seconds": "60", "max_output_bytes": 1024.0}
    )
    assert (command.timeout_seconds, command.max_output_bytes) == (60, 1024)
    assert EnvironmentCommand.from_mapping({"argv": ["python"]}).timeout_seconds == 60


@pytest.mark.parametrize("provider_type", [LocalSandboxProvider, OCIContainerProvider])
@pytest.mark.parametrize("corruption", ["cpu", "timeout", "output"])
def test_direct_provider_execution_revalidates_constructed_contracts(
    tmp_path, provider_type, corruption
):
    calls = []
    provider = provider_type(runner=lambda *args: calls.append(args))
    environment = ExecutionEnvironment.from_mapping({}, new_identity=True)
    command = EnvironmentCommand(argv=("python",))
    if corruption == "cpu":
        environment = replace(environment, cpu_limit=float("nan"))
    else:
        command = replace(
            command,
            **{"timeout_seconds" if corruption == "timeout" else "max_output_bytes": 0},
        )
    with pytest.raises(EnvironmentValidationError):
        provider.execute(environment, str(tmp_path), command)
    assert not calls
    assert not list(tmp_path.iterdir())


def test_oci_prepare_rejects_constructed_limit_and_retains_default_pid64(tmp_path):
    calls = []
    provider = OCIContainerProvider(
        engine_path="docker", runner=lambda *args: calls.append(args)
    )
    environment = ExecutionEnvironment.from_mapping(
        {"environment_type": "oci_container", "provider": "oci", "image": "fake"},
        new_identity=True,
    )
    with pytest.raises(EnvironmentValidationError, match="cpu_limit"):
        provider.prepare(replace(environment, cpu_limit=float("nan")), tmp_path)
    assert not calls
    argv = provider.build_create_command(environment, tmp_path)
    assert argv[argv.index("--pids-limit") + 1] == "64"
    assert argv[argv.index("--cpus") + 1] == "1.0"
    assert argv[argv.index("--memory") + 1] == "512m"


def test_restart_rejects_invalid_record_even_with_its_matching_digest(tmp_path):
    provider = OCIContainerProvider(engine_path="docker")
    runtime = EnvironmentRuntime(
        tmp_path, providers=EnvironmentProviderRegistry({"oci": provider})
    )
    record = runtime.create(
        {"environment_type": "oci_container", "provider": "oci", "image": "fake"}
    )
    environment = ExecutionEnvironment.from_mapping(
        {
            k: v
            for k, v in record.items()
            if k not in {"sha256", "artifact_id", "operation_run_id", "compatibility"}
        }
    )
    invalid = replace(environment, cpu_limit=float("nan"))
    runtime._environment_path(environment.environment_id).write_text(
        json.dumps({**invalid.to_dict(), "sha256": invalid.digest()})
    )
    restarted = EnvironmentRuntime(
        tmp_path, providers=EnvironmentProviderRegistry({"oci": provider})
    )
    assert restarted.list_environments()[0]["state"] == "invalid"
    with pytest.raises(EnvironmentValidationError, match="cpu_limit"):
        restarted.start(environment.environment_id)
