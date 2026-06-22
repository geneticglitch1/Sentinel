"""Dry-run + confirm gating.

The rule, in one place:

  * Every mutating tool defaults to a dry run — it returns the planned change and
    touches nothing unless ``confirm=True``.
  * A change flagged ``destructive`` (delete VM, drop a firewall rule, rm a
    container, retune IDS) *refuses* to run without an explicit confirm — it raises
    ``ConfirmationRequired`` rather than quietly planning.

This is deliberately strict. The cowork log has a self-inflicted firewall lockout
in it; the whole point of the gate is that one bad model turn can't repeat that.
"""

from __future__ import annotations

from .models import PlannedChange


class ConfirmationRequired(Exception):
    """Raised when a destructive change is attempted without confirm=True."""

    def __init__(self, planned: PlannedChange):
        self.planned = planned
        super().__init__(
            f"Refusing destructive action without confirm=True: {planned.summary}"
        )


def gate(planned: PlannedChange, confirm: bool) -> bool:
    """Decide whether to apply a change.

    Returns ``True`` if the caller should apply it, ``False`` for a dry run.
    Raises :class:`ConfirmationRequired` for a destructive change without confirm.
    """
    if planned.destructive and not confirm:
        raise ConfirmationRequired(planned)
    return confirm
