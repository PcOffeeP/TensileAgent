"""Deterministic V4.1 event-bound updates shared by Agent strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_LATER_STATES = {"未断裂", "临界未断裂"}
_EARLIER_STATES = {"已断裂"}
_WITHIN_STATES = {"发生断裂"}
_NO_DIRECTION_STATES = {"无法判断"}
V4_1_CLIP_STATES = (
    _LATER_STATES | _EARLIER_STATES | _WITHIN_STATES | _NO_DIRECTION_STATES
)


@dataclass(frozen=True)
class EventBoundsUpdate:
    """One immutable account of an attempted event-bound update."""

    changed: bool
    conflict: bool
    conflict_resolved: bool
    direction: str | None
    bounds: tuple[float, float]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "conflict": self.conflict,
            "conflict_resolved": self.conflict_resolved,
            "direction": self.direction,
            "bounds": list(self.bounds),
            "reason": self.reason,
        }


@dataclass
class V41EventBounds:
    """Monotonic trustworthy event interval for one V4.1 task.

    Sampling ranges may expand for exploration, but this interval never does.
    Contradictory updates are recorded and rejected instead of overwriting the
    last trustworthy bounds.
    """

    lower: float
    upper: float
    unresolved_conflict: bool = False
    conflict_count: int = 0
    pending_conflict_ranges: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lower = float(self.lower)
        self.upper = float(self.upper)
        if not self.lower < self.upper:
            raise ValueError("event bounds must satisfy lower < upper")

    @property
    def interval(self) -> list[float]:
        return [self.lower, self.upper]

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def publishable(self, tolerance_seconds: float) -> bool:
        return (
            not self.unresolved_conflict
            and self.lower < self.upper
            and self.width <= float(tolerance_seconds) + 1e-9
        )

    def apply(self, clip_state: str, sample_range: Any) -> EventBoundsUpdate:
        """Apply one direction result without ever expanding trusted bounds."""
        if clip_state not in V4_1_CLIP_STATES:
            raise ValueError(f"unsupported V4.1 clip_state: {clip_state}")
        if (
            not isinstance(sample_range, list)
            or len(sample_range) != 2
            or not all(isinstance(value, (int, float)) for value in sample_range)
        ):
            raise ValueError("sample_range must be a numeric [start, end] list")
        start, end = float(sample_range[0]), float(sample_range[1])
        if not start < end:
            raise ValueError("sample_range must satisfy start < end")

        if clip_state in _NO_DIRECTION_STATES:
            return EventBoundsUpdate(
                changed=False,
                conflict=False,
                conflict_resolved=False,
                direction=None,
                bounds=(self.lower, self.upper),
                reason="no_direction",
            )

        direction: str
        proposed_lower = self.lower
        proposed_upper = self.upper
        if clip_state in _LATER_STATES:
            direction = "later"
            proposed_lower = max(self.lower, end)
        elif clip_state in _EARLIER_STATES:
            direction = "earlier"
            proposed_upper = min(self.upper, start)
        else:
            direction = "within"
            proposed_lower = max(self.lower, start)
            proposed_upper = min(self.upper, end)

        if proposed_lower >= proposed_upper:
            self.unresolved_conflict = True
            self.conflict_count += 1
            self.pending_conflict_ranges.append((start, end))
            return EventBoundsUpdate(
                changed=False,
                conflict=True,
                conflict_resolved=False,
                direction=direction,
                bounds=(self.lower, self.upper),
                reason="empty_intersection_rejected",
            )

        changed = (
            proposed_lower > self.lower + 1e-9
            or proposed_upper < self.upper - 1e-9
        )
        self.lower = proposed_lower
        self.upper = proposed_upper
        conflict_resolved = False
        if clip_state in _WITHIN_STATES and self.unresolved_conflict:
            for index, pending in enumerate(self.pending_conflict_ranges):
                if (
                    abs(start - pending[0]) <= 1e-9
                    and abs(end - pending[1]) <= 1e-9
                ):
                    self.pending_conflict_ranges.pop(index)
                    self.conflict_count -= 1
                    self.unresolved_conflict = bool(self.pending_conflict_ranges)
                    conflict_resolved = True
                    break
        return EventBoundsUpdate(
            changed=changed,
            conflict=False,
            conflict_resolved=conflict_resolved,
            direction=direction,
            bounds=(self.lower, self.upper),
            reason="contracted" if changed else "no_op",
        )
