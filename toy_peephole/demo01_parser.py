"""demo01_parser.py — Minimal RISC-V Assembly Parser.

Parses assembly into the tuple representation used by the toy peephole engine:

- instruction: ``(opcode, [operands])``
- label: ``(None, [label])``
- inline label: ``((None, [label]), (opcode, [operands]))``

Usage:
    python -m toy_peephole.demo01_parser --file test.s
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_LABEL_RE = re.compile(
    r"^(?P<label>(?:[A-Za-z_.$][A-Za-z0-9_.$]*|[0-9]+)):(?P<rest>.*)$",
)


def _strip_comment(line: str) -> str:
    """Remove an assembly comment without truncating quoted directive data."""
    quote: str | None = None
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:index]

    return line


def _split_operands(text: str) -> list[str]:
    """Split operands while preserving parentheses and quoted strings."""
    if not text:
        return []

    operands: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False

    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if quote is not None:
            current.append(char)
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            current.append(char)
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            operand = "".join(current).strip()
            if operand:
                operands.append(operand)
            current = []
            continue
        current.append(char)

    operand = "".join(current).strip()
    if operand:
        operands.append(operand)

    return operands


def _parse_instruction(text: str) -> tuple[str, list[str]] | None:
    """Parse an instruction without a leading label or trailing comment."""
    parts = text.split(None, 1)
    if not parts:
        return None

    opcode = parts[0].lower()
    operands = _split_operands(parts[1].strip()) if len(parts) == 2 else []
    return opcode, operands


def parse_line(line: str) -> tuple | None:
    """Parse one assembly line, skipping blank and comment-only lines."""
    code = _strip_comment(line).strip()
    if not code:
        return None

    label_match = _LABEL_RE.match(code)
    if label_match is None:
        return _parse_instruction(code)

    label = (None, [label_match.group("label")])
    remainder = label_match.group("rest").strip()
    if not remainder:
        return label

    instruction = _parse_instruction(remainder)
    if instruction is None:
        return label
    return label, instruction


def parse_asm(text: str) -> list[tuple]:
    """Parse assembly text into instructions and labels."""
    parsed: list[tuple] = []
    for line in text.splitlines():
        entry = parse_line(line)
        if entry is not None:
            parsed.append(entry)
    return parsed


def _instruction_to_asm(instruction: tuple[str, list[str]]) -> str:
    """Render one instruction using canonical indentation and commas."""
    opcode, operands = instruction
    if not operands:
        return f"  {opcode}"
    return f"  {opcode} {', '.join(operands)}"


def lines_to_asm(lines: list[tuple]) -> str:
    """Render parsed instructions and labels as canonical assembly text."""
    output: list[str] = []

    for entry in lines:
        first, second = entry
        if first is None:
            output.append(f"{second[0]}:")
        elif isinstance(first, tuple):
            label = first[1][0]
            output.append(f"{label}:{_instruction_to_asm(second)}")
        else:
            output.append(_instruction_to_asm(entry))

    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse RISC-V assembly into peephole tuples",
    )
    parser.add_argument(
        "--file",
        type=Path,
        required=True,
        help="Assembly file to parse",
    )
    args = parser.parse_args()

    for entry in parse_asm(args.file.read_text(encoding="utf-8")):
        print(entry)


if __name__ == "__main__":
    main()
