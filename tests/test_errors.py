"""Runtime Foundation error hierarchy tests."""

import pytest

from nous_runtime import errors as public_errors
from nous_runtime.core.errors import (
    ArtifactError,
    CapabilityError,
    ConfigurationError,
    NousError,
    ProviderError,
    RuntimeStateError,
    TaskError,
)


@pytest.mark.parametrize(
    "error_type",
    [
        ConfigurationError,
        ProviderError,
        CapabilityError,
        TaskError,
        RuntimeStateError,
        ArtifactError,
    ],
)
def test_foundation_errors_inherit_from_nous_error(error_type):
    assert issubclass(error_type, NousError)


def test_foundation_error_can_be_caught_by_base_and_keeps_message():
    with pytest.raises(NousError, match="provider unavailable") as captured:
        raise ProviderError("provider unavailable")

    assert str(captured.value) == "provider unavailable"


def test_historical_error_module_reexports_foundation_types():
    assert public_errors.NousError is NousError
    assert public_errors.ConfigurationError is ConfigurationError
    assert public_errors.ProviderError is ProviderError
    assert public_errors.ArtifactError is ArtifactError


def test_replacement_errors_preserve_legacy_catch_categories():
    assert issubclass(ConfigurationError, ValueError)
    assert issubclass(ProviderError, ValueError)
    assert issubclass(TaskError, ValueError)
    assert issubclass(RuntimeStateError, ValueError)
    assert issubclass(CapabilityError, LookupError)
