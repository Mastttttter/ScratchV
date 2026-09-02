"""demo02_engine.py — Peephole Rule Engine for RISC-V Assembly.

Toy implementation: sliding-window peephole optimizer with 6 rules.
Built on demo01_parser.py for assembly parsing.

Usage:
    python -m toy_peephole.demo02_engine --input test.s
    python -m toy_peephole.demo02_engine --input test.s --check
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from toy_peephole.demo01_parser import lines_to_asm, parse_asm, parse_line

# ---------------------------------------------------------------------------
# PeepholeRule dataclass
# ---------------------------------------------------------------------------


@dataclass
class PeepholeRule:
    """A single peephole optimization rule.

    name: Human-readable name (e.g. "addi+addi fusion")
    pattern: List of opcodes to match (e.g. ["addi", "addi"])
    condition: Function (parsed_lines_window) -> bool, or None for unconditional
    replacement: Function (parsed_lines_window) -> [output_strings]
    """

    name: str
    pattern: list[str]
    replacement: Callable[[list], list[str]]
    condition: Callable[[list], bool] | None = None


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------


def _entry_opcode(entry) -> str | None:
    """Extract the opcode string from a parsed entry, if it is an instruction.

    Handles: (opcode, [operands]), (None, [label]),
    and ((None, [label]), (opcode, [operands])) inline label+instruction.
    """
    if entry is None:
        return None
    if not isinstance(entry, tuple) or len(entry) != 2:
        return None
    # (None, [label]) — label only
    if entry[0] is None:
        return None
    # ((None, [label]), (opcode, [operands])) — inline label + instruction
    if isinstance(entry[0], tuple):
        inner = entry[1]
        if isinstance(inner, tuple) and len(inner) == 2:
            return inner[0]
        return None
    # (opcode, [operands]) — plain instruction
    return entry[0]


def _entry_operands(entry) -> list[str] | None:
    """Extract the operand list from a parsed entry, if it is an instruction."""
    if entry is None:
        return None
    if not isinstance(entry, tuple) or len(entry) != 2:
        return None
    # (None, [label])
    if entry[0] is None:
        return None
    # ((None, [label]), (opcode, [operands]))
    if isinstance(entry[0], tuple):
        inner = entry[1]
        if isinstance(inner, tuple) and len(inner) == 2:
            return inner[1]
        return None
    # (opcode, [operands])
    return entry[1]


def _entry_label(entry) -> str | None:
    """Extract a standalone or inline label from a parsed entry."""
    if not isinstance(entry, tuple) or len(entry) != 2:
        return None

    if entry[0] is None:
        labels = entry[1]
    elif isinstance(entry[0], tuple):
        label_entry = entry[0]
        if len(label_entry) != 2 or label_entry[0] is not None:
            return None
        labels = label_entry[1]
    else:
        return None

    if not isinstance(labels, list) or not labels:
        return None
    return labels[0]


def _window_matches(window: list, rule: PeepholeRule) -> bool:
    """Check if a parsed window matches a rule's opcode pattern + condition.

    Only counts instruction entries (skips labels in the window when matching
    opcode positions). If the window contains fewer instructions than the
    pattern length, the match fails.
    """
    # Never optimize across a control-flow target inside the window.
    if any(_entry_label(entry) is not None for entry in window[1:]):
        return False

    # Collect non-label entries (instructions only)
    instr_indices = []
    for j, entry in enumerate(window):
        opcode = _entry_opcode(entry)
        if opcode is not None:
            instr_indices.append(j)

    if len(instr_indices) < len(rule.pattern):
        return False

    # Match opcodes against pattern — first instr_indices of window
    # must have the correct opcode sequence
    for k, idx in enumerate(instr_indices[: len(rule.pattern)]):
        opcode = _entry_opcode(window[idx])
        if opcode is None or opcode != rule.pattern[k]:
            return False

    # Check condition on the full window
    if rule.condition is not None and not rule.condition(window):
        return False

    return True


def _reparse(strings: list[str]) -> list:
    """Re-parse a list of assembly instruction strings into parsed tuples."""
    result: list = []
    for s in strings:
        parsed = parse_line(s)
        if parsed is not None:
            result.append(parsed)
    return result


# ---------------------------------------------------------------------------
# Core engine: single-pass sliding window
# ---------------------------------------------------------------------------


def peephole_pass(
    lines: list,
    rules: list[PeepholeRule],
) -> tuple[list, int, dict[str, int]]:
    """Single-pass sliding-window peephole optimization.

    For each position *i* in *lines*, attempt each rule in order.
    If a rule matches the window ``lines[i:i+len(rule.pattern)]``,
    the window is replaced with the rule's replacement output and
    scanning restarts from position *i*.

    Args:
        lines: Parsed assembly tuples from parse_asm().
        rules: Ordered list of PeepholeRule to apply.

    Returns:
        (new_lines, total_changes, per_rule_counts).
    """
    new_lines = list(lines)
    changes = 0
    rule_matches: dict[str, int] = {r.name: 0 for r in rules}
    i = 0

    while i < len(new_lines):
        matched = False
        for rule in rules:
            window_size = len(rule.pattern)
            if i + window_size > len(new_lines):
                continue

            window = new_lines[i : i + window_size]

            if _window_matches(window, rule):
                replacement_strs = rule.replacement(window)
                replacement_lines = _reparse(replacement_strs)
                label = _entry_label(window[0])
                if label is not None:
                    if replacement_lines:
                        replacement_lines[0] = (
                            (None, [label]),
                            replacement_lines[0],
                        )
                    else:
                        replacement_lines = [(None, [label])]
                new_lines[i : i + window_size] = replacement_lines
                changes += 1
                rule_matches[rule.name] += 1
                matched = True
                # Restart scan from current position
                break

        if not matched:
            i += 1

    return new_lines, changes, rule_matches


# ---------------------------------------------------------------------------
# Default rules
# ---------------------------------------------------------------------------


_ZERO_REGISTERS = {"x0", "zero"}
_ADDI_MIN = -(1 << 11)
_ADDI_MAX = (1 << 11) - 1


def _op(entry, idx: int) -> str:
    """Safely extract the *idx*-th operand from an instruction entry."""
    ops = _entry_operands(entry)
    assert ops is not None and idx < len(ops), (
        f"operand index {idx} out of range for {entry}"
    )
    return ops[idx]


def _parse_immediate(value: str) -> int | None:
    """Parse decimal or prefixed integer immediates used by toy rules."""
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(value, 10)
        except ValueError:
            return None


def get_default_rules() -> list[PeepholeRule]:
    """Return the six default peephole optimization rules."""

    # Rule 1: addi rd, rs, a; addi rd, rd, b  →  addi rd, rs, (a+b)
    def _addi_addi_condition(w: list) -> bool:
        imm_a = _parse_immediate(_op(w[0], 2))
        imm_b = _parse_immediate(_op(w[1], 2))
        if imm_a is None or imm_b is None:
            return False
        return (
            _op(w[0], 0) == _op(w[1], 1)
            and _op(w[0], 0) == _op(w[1], 0)
            and _ADDI_MIN <= imm_a + imm_b <= _ADDI_MAX
        )

    def _addi_addi_replacement(w: list) -> list[str]:
        imm_a = _parse_immediate(_op(w[0], 2))
        imm_b = _parse_immediate(_op(w[1], 2))
        assert imm_a is not None and imm_b is not None
        return [
            f"addi {_op(w[0], 0)}, {_op(w[0], 1)}, {imm_a + imm_b}",
        ]

    # Rule 2: li rd, a; addi rd, rd, b  →  li rd, (a+b)
    def _li_addi_condition(w: list) -> bool:
        return (
            _op(w[0], 0) == _op(w[1], 1)
            and _op(w[0], 0) == _op(w[1], 0)
            and _parse_immediate(_op(w[0], 1)) is not None
            and _parse_immediate(_op(w[1], 2)) is not None
        )

    def _li_addi_replacement(w: list) -> list[str]:
        imm_a = _parse_immediate(_op(w[0], 1))
        imm_b = _parse_immediate(_op(w[1], 2))
        assert imm_a is not None and imm_b is not None
        return [
            f"li {_op(w[0], 0)}, {imm_a + imm_b}",
        ]

    # Rule 3: beq x0/zero, x0/zero, label  →  j label
    def _beq_zero_condition(w: list) -> bool:
        return _op(w[0], 0) in _ZERO_REGISTERS and _op(w[0], 1) in _ZERO_REGISTERS

    def _beq_zero_replacement(w: list) -> list[str]:
        return [f"j {_op(w[0], 2)}"]

    # Rule 4: mv a, b; mv b, a  →  mv a, b
    def _mv_swap_condition(w: list) -> bool:
        return (
            _op(w[0], 0) not in _ZERO_REGISTERS
            and _op(w[0], 0) == _op(w[1], 1)
            and _op(w[0], 1) == _op(w[1], 0)
        )

    def _mv_swap_replacement(w: list) -> list[str]:
        return [f"mv {_op(w[0], 0)}, {_op(w[0], 1)}"]

    # Rule 5: keep mv a, b; rewrite mv c, a  →  mv c, b
    def _mv_chain_condition(w: list) -> bool:
        return (
            _op(w[0], 0) not in _ZERO_REGISTERS
            and _op(w[0], 0) != _op(w[0], 1)
            and _op(w[0], 0) == _op(w[1], 1)
        )

    def _mv_chain_replacement(w: list) -> list[str]:
        return [
            f"mv {_op(w[0], 0)}, {_op(w[0], 1)}",
            f"mv {_op(w[1], 0)}, {_op(w[0], 1)}",
        ]

    # Rule 6: addi rd, rd, 0  →  delete
    def _addi_zero_condition(w: list) -> bool:
        return _op(w[0], 0) == _op(w[0], 1) and _parse_immediate(_op(w[0], 2)) == 0

    def _addi_zero_replacement(w: list) -> list[str]:
        return []

    return [
        PeepholeRule(
            name="addi+addi fusion",
            pattern=["addi", "addi"],
            condition=_addi_addi_condition,
            replacement=_addi_addi_replacement,
        ),
        PeepholeRule(
            name="li+addi fusion",
            pattern=["li", "addi"],
            condition=_li_addi_condition,
            replacement=_li_addi_replacement,
        ),
        PeepholeRule(
            name="beq zero-zero to j",
            pattern=["beq"],
            condition=_beq_zero_condition,
            replacement=_beq_zero_replacement,
        ),
        PeepholeRule(
            name="mv swap elimination",
            pattern=["mv", "mv"],
            condition=_mv_swap_condition,
            replacement=_mv_swap_replacement,
        ),
        PeepholeRule(
            name="mv chain shortening",
            pattern=["mv", "mv"],
            condition=_mv_chain_condition,
            replacement=_mv_chain_replacement,
        ),
        PeepholeRule(
            name="addi zero elimination",
            pattern=["addi"],
            condition=_addi_zero_condition,
            replacement=_addi_zero_replacement,
        ),
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Peephole Optimizer — Demo 02: Rule Engine + 6 Rules",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to RISC-V assembly file",
    )
    parser.add_argument(
        "--check",
        "-c",
        action="store_true",
        help="Print before/after assembly",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    text = input_path.read_text()
    parsed = parse_asm(text)
    before_text = lines_to_asm(parsed)

    rules = get_default_rules()
    optimized, changes, rule_matches = peephole_pass(parsed, rules)
    after_text = lines_to_asm(optimized)

    if args.check:
        print("=== Before ===")
        print(before_text)
        print()
        print("=== After ===")
        print(after_text)
        print()

    print(f"Changes: {changes}")
    for name, count in rule_matches.items():
        if count > 0:
            print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
