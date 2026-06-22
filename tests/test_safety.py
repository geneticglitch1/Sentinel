import pytest

from sentinel.models import PlannedChange
from sentinel.safety import ConfirmationRequired, gate


def _pc(destructive=False):
    return PlannedChange(tool="x", summary="do thing", destructive=destructive)


def test_nondestructive_defaults_to_dry_run():
    assert gate(_pc(), confirm=False) is False


def test_nondestructive_applies_with_confirm():
    assert gate(_pc(), confirm=True) is True


def test_destructive_without_confirm_raises():
    with pytest.raises(ConfirmationRequired):
        gate(_pc(destructive=True), confirm=False)


def test_destructive_with_confirm_applies():
    assert gate(_pc(destructive=True), confirm=True) is True
