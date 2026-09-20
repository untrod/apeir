import platform

from nous_runtime.yaml_compat import yaml


def test_yaml_compat_round_trip():
    payload = {"models": [{"id": "local", "enabled": True}]}
    assert yaml.safe_load(yaml.safe_dump(payload)) == payload


def test_arm_uses_pure_python_yaml_loader():
    if platform.machine().strip().lower() in {"arm64", "aarch64"}:
        assert yaml.SafeLoader.__module__ == "yaml.loader"
