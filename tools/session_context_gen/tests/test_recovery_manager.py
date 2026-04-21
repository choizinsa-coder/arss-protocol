import pytest
from tools.session_context_gen.recovery_manager import RecoveryError, recover_baseline


def test_T8_recovery_raises_not_implemented():
    """T8: recovery call — RecoveryError raised (stub confirmed)."""
    with pytest.raises(RecoveryError, match="Recovery requires explicit Beo-approved artifact"):
        recover_baseline()


def test_recovery_with_args_raises():
    with pytest.raises(RecoveryError):
        recover_baseline("some_arg", key="value")


def test_recovery_error_message():
    with pytest.raises(RecoveryError) as exc_info:
        recover_baseline()
    assert "EAG-1" in str(exc_info.value)
    assert "Not yet implemented" in str(exc_info.value)
