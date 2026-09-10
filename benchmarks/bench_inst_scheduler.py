"""Benchmark legal physical-register regions through the production scheduler.

Run: python -m benchmarks.bench_inst_scheduler --repeats 20 --json report.json
Reported cycles are sums of local static model estimates, not CPU measurements.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from scratchv.backend.inst_scheduler import (
    InstructionScheduler,
    SchedInst,
    ScheduleConfig,
    schedule_assembly,
)


def _gen_instructions(
    num_insts: int, seed: int = 42, dep_chains: int = 3
) -> list[SchedInst]:
    """Generate real opcodes/operands; keep a0 as an unchanged memory base."""
    rng = random.Random(seed)
    registers = [f"x{i}" for i in list(range(5, 10)) + list(range(11, 32))]
    chain_count = max(1, min(dep_chains, len(registers)))
    groups = [registers[i::chain_count] for i in range(chain_count)]
    previous = [group[0] for group in groups]
    instructions = []
    for index in range(num_insts):
        chain = index % chain_count
        dst, src = rng.choice(groups[chain]), previous[chain]
        op = rng.choice(["add", "sub", "mul", "div", "lw", "sw", "addi", "li", "mv"])
        if op in {"lw", "sw"}:
            operands = [dst, f"{rng.randrange(8) * 4}(a0)"]
        elif op == "li":
            operands = [dst, str(rng.randrange(-100, 100))]
        elif op == "mv":
            operands = [dst, src]
        elif op == "addi":
            operands = [dst, src, str(rng.randrange(-16, 16))]
        else:
            operands = [dst, src, rng.choice(groups[chain])]
        instructions.append(
            SchedInst(index, op, operands, raw_line=f"  {op} " + ", ".join(operands))
        )
        if op != "sw":
            previous[chain] = dst
    return instructions


def bench_build_dag(insts: list[SchedInst], repeats: int = 20) -> dict:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        dag = InstructionScheduler().build_dag(insts)
        times.append(time.perf_counter() - start)
    return {"num_nodes": len(dag), "mean_s": statistics.mean(times)}


def bench_schedule(
    insts: list[SchedInst], repeats: int = 20, max_region_size: int = 1024
) -> dict:
    source = "\n".join(inst.raw_line for inst in insts) + "\n"
    times = []
    config = ScheduleConfig(strict=True, max_region_size=max_region_size)
    for _ in range(repeats):
        start = time.perf_counter()
        result = schedule_assembly(source, config)
        times.append(time.perf_counter() - start)
    stats = result.stats
    return {
        "num_insts": len(insts),
        "orig_cycles": stats["original_cycles"],
        "sched_cycles": stats["final_cycles"],
        "improvement": stats["saved_cycles"],
        "modeled": stats["modeled_instructions"],
        "skipped": stats["skipped_regions"],
        "moved": stats["moved_instructions"],
        "model": stats["model"],
        "mean_s": statistics.mean(times),
        "stdev_s": statistics.stdev(times) if repeats > 1 else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--max-region-size", type=int, default=1024)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.max_region_size < 1:
        parser.error("repeats and max-region-size must be positive")
    records = []
    print("Local static model estimates; not measured hardware cycles")
    print(
        f"{'Size':>6} {'Time(ms)':>10} {'Before':>8} {'After':>8} {'Saved':>8} {'Modeled':>8} {'Skipped':>8}"
    )
    for size in [10, 50, 100, 200, 500, 1000, 5000]:
        row = bench_schedule(
            _gen_instructions(size), args.repeats, args.max_region_size
        )
        records.append(row)
        print(
            f"{size:6} {row['mean_s'] * 1000:10.3f} {row['orig_cycles']:8} "
            f"{row['sched_cycles']:8} {row['improvement']:8} {row['modeled']:8} {row['skipped']:8}"
        )
    if args.json:
        args.json.write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    main()
