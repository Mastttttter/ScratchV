"""Single-issue teaching model shared by scheduling and order estimation.

These are local static estimates, not hardware cycles or the existing
five-stage PipelineCycleEstimator's stage occupancy counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from .schedule_semantics import DIVIDE, LOADS, MULTIPLY, SchedInst, ScheduleError


@dataclass(frozen=True)
class Timing:
    latency: int = 1
    resource: str = "alu"
    occupancy: int = 1


@dataclass(frozen=True)
class ScheduleModel:
    name: str = "scratchv-single-issue-v1"
    overrides: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = dict(self.overrides)
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 1
            for v in values.values()
        ):
            raise ValueError("Scheduling latencies must be positive integers")
        object.__setattr__(self, "overrides", MappingProxyType(values))

    def timing(self, inst: SchedInst) -> Timing:
        if inst.effects.barrier_reason:
            raise ScheduleError(
                f"Cannot estimate {inst.opcode}: {inst.effects.barrier_reason}"
            )
        op = inst.opcode
        latency, resource, occupancy = 1, "alu", 1
        if inst.effects.memory != "none":
            latency, resource = (2 if op in LOADS else 1), "memory"
        elif op in MULTIPLY:
            latency, resource = 3, "multiply"
        elif op in DIVIDE:
            latency, resource, occupancy = 16, "divide", 16
        elif inst.terminator:
            resource = "branch"
        elif op.startswith("f"):
            resource = "float"
            double = op.endswith(".d") or op.startswith("fcvt.d.")
            stem = op.split(".")[0]
            if stem in {"fdiv", "fsqrt"}:
                latency = 16 if double else 12
                resource, occupancy = "float-divide", latency
            elif stem in {"fmul", "fmadd", "fmsub", "fnmadd", "fnmsub"}:
                latency = 5 if double else 4
            elif stem in {"fadd", "fsub", "fcvt"}:
                latency = 4 if double else 3
            elif stem in {"fmin", "fmax", "feq", "flt", "fle"}:
                latency = 3 if double else 2
        latency = self.overrides.get(op, latency)
        if resource in {"divide", "float-divide"}:
            occupancy = latency
        return Timing(latency, resource, occupancy)


@dataclass(frozen=True)
class OrderEstimate:
    cycles: int
    stalls: int
    issue_cycles: tuple[int, ...]


def estimate_order(
    instructions: Sequence[SchedInst], model: ScheduleModel | None = None
) -> OrderEstimate:
    """Simulate this exact order, independently of graph/scheduler state."""
    model = model or ScheduleModel()
    ready: dict[str, int] = {}
    resources: dict[str, int] = {}
    next_issue = completion = stalls = 0
    issues = []
    for inst in instructions:
        timing = model.timing(inst)
        issue = max(
            next_issue,
            resources.get(timing.resource, 0),
            max((ready.get(reg, 0) for reg in inst.uses), default=0),
        )
        stalls += issue - next_issue
        issues.append(issue)
        for reg in inst.defines:
            ready[reg] = issue + timing.latency
        resources[timing.resource] = issue + timing.occupancy
        completion = max(completion, issue + timing.latency)
        next_issue = issue + 1
    return OrderEstimate(completion, stalls, tuple(issues))
