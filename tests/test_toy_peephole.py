"""Tests for all 6 peephole rules (Toy Peephole Optimizer).

Rules under test:
  1. addi+addi fusion:  addi rd, rs, a; addi rd, rd, b → addi rd, rs, (a+b)
  2. li+addi fusion:    li rd, a; addi rd, rd, b → li rd, (a+b)
  3. beq x0→j:          beq x0/zero, x0/zero, label → j label
  4. mv reverse copy:   mv x,y; mv y,x → keep the first copy
  5. mv chain:          keep mv a,b; rewrite mv c,a → mv c,b
  6. addi zero:         addi rd, rd, 0 → delete

See docs/topics/toy-peephole/02-rules-and-iteration.md for rationale.
"""

from toy_peephole.demo01_parser import lines_to_asm, parse_asm, parse_line
from toy_peephole.demo02_engine import get_default_rules, peephole_pass

RULES = get_default_rules()  # 6 peephole rules


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    """Assembly text is parsed into the tuple format consumed by the engine."""

    def test_instruction(self):
        assert parse_line("addi x1, x2, 3") == (
            "addi",
            ["x1", "x2", "3"],
        )

    def test_label(self):
        assert parse_line("main:") == (None, ["main"])

    def test_comments_and_empty_lines_are_skipped(self):
        asm = "\n# heading\naddi x1, x2, 3  # comment\n"
        assert parse_asm(asm) == [("addi", ["x1", "x2", "3"])]

    def test_inline_label(self):
        assert parse_line("loop: addi x1, x1, -1") == (
            (None, ["loop"]),
            ("addi", ["x1", "x1", "-1"]),
        )

    def test_numeric_and_dollar_labels(self):
        assert parse_line("1: addi x1, x1, -1") == (
            (None, ["1"]),
            ("addi", ["x1", "x1", "-1"]),
        )
        assert parse_line("$start:") == (None, ["$start"])

    def test_quoted_directive_data(self):
        directive = '.string "a,b#c"'
        assert lines_to_asm([parse_line(directive)]) == f"  {directive}"

    def test_round_trip(self):
        asm = "main:\n  lw x1, 0(x2)\n  ret\n"
        assert lines_to_asm(parse_asm(asm)) == ("main:\n  lw x1, 0(x2)\n  ret")


# ---------------------------------------------------------------------------
# Rule 1: addi+addi fusion
# ---------------------------------------------------------------------------


class TestAddiAddiFusion:
    """addi rd, rs, a; addi rd, rd, b → addi rd, rs, (a+b)."""

    def test_fusion_basic(self):
        """Two consecutive addi with same rd,rs → merged immediate."""
        asm = "  addi x1, x1, 3\n  addi x1, x1, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "8" in output  # 3 + 5 = 8
        assert output.count("addi") == 1  # merged

    def test_fusion_negative_imm(self):
        """Negative immediate fusion: 3 + (-5) = -2."""
        asm = "  addi x2, x2, 3\n  addi x2, x2, -5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "-2" in output  # 3 + (-5) = -2

    def test_fusion_dependency_chain_with_distinct_source(self):
        """The first source may differ from the shared destination."""
        asm = "  addi x1, x2, 3\n  addi x1, x1, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "  addi x1, x2, 8"

    def test_fusion_prefixed_immediates(self):
        """Prefixed integer immediates are folded numerically."""
        asm = "  addi x1, x1, 0x3\n  addi x1, x1, 0x5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "  addi x1, x1, 8"

    def test_no_fusion_when_sum_exceeds_addi_range(self):
        """A fused addi must retain a valid signed 12-bit immediate."""
        asm = "  addi x1, x1, 2047\n  addi x1, x1, 1\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_no_fusion_different_rd(self):
        """Different rd → no fusion (no data dependency)."""
        asm = "  addi x1, x2, 3\n  addi x3, x4, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_no_fusion_identical_ops(self):
        """Same rd but different rs → no fusion (condition checks both)."""
        asm = "  addi x1, x2, 3\n  addi x1, x3, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_no_fusion_separate_blocks(self):
        """Non-consecutive addi → no fusion (pattern length mismatch)."""
        asm = "  addi x1, x1, 3\n  nop\n  addi x1, x1, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Rule 2: li+addi fusion
# ---------------------------------------------------------------------------


class TestLiAddiFusion:
    """li rd, a; addi rd, rd, b → li rd, (a+b)."""

    def test_fusion_basic(self):
        """li + addi with same rd → merged immediate."""
        asm = "  li x1, 10\n  addi x1, x1, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "15" in output  # 10 + 5 = 15
        assert "li" in output
        assert "addi" not in output  # addi eliminated

    def test_fusion_zero_imm(self):
        """Zero immediate: 7 + 0 = 7."""
        asm = "  li x5, 7\n  addi x5, x5, 0\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "7" in output

    def test_no_fusion_no_chain(self):
        """No data dependency → no fusion."""
        asm = "  li x1, 10\n  addi x2, x3, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_no_fusion_diff_regs(self):
        """li.rd != addi.rd → no fusion."""
        asm = "  li x1, 10\n  addi x2, x1, 5\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Rule 3: beq x0/zero → j
# ---------------------------------------------------------------------------


class TestBeqToJ:
    """beq x0/zero, x0/zero, label → j label."""

    def test_beq_x0_to_j(self):
        """beq x0, x0 → j."""
        asm = "  beq x0, x0, loop\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "j" in output
        assert "loop" in output
        assert "beq" not in output

    def test_beq_zero_alias(self):
        """beq zero, zero → j (zero alias)."""
        asm = "  beq zero, zero, end\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "j" in output
        assert "end" in output

    def test_beq_x0_zero_mixed(self):
        """beq x0, zero → j (mixed aliases)."""
        asm = "  beq x0, zero, target\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "j target" in output

    def test_no_match_nonzero(self):
        """beq with non-zero register → no match."""
        asm = "  beq x1, x0, loop\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_no_match_both_nonzero(self):
        """beq with both non-zero registers → no match."""
        asm = "  beq x5, x6, loop\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Label preservation
# ---------------------------------------------------------------------------


class TestLabelPreservation:
    """Labels before instructions are preserved after optimization."""

    def test_label_before_fusion(self):
        """Standalone label before a fusable pair is preserved."""
        asm = "main:\n  addi x1, x1, 3\n  addi x1, x1, 5\n  ret\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "main:" in output

    def test_label_before_beq(self):
        """Label before beq→j conversion preserved."""
        asm = "start:\n  beq x0, x0, end\nend:\n  ret\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes >= 1
        output = lines_to_asm(result)
        assert "start:" in output
        assert "end:" in output
        assert "j end" in output

    def test_inline_label_on_replaced_instruction(self):
        """An inline control-flow target remains attached after replacement."""
        asm = "loop: beq x0, x0, done\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "loop:  j done"

    def test_inline_label_on_deleted_instruction(self):
        """Deleting a no-op instruction leaves its label behind."""
        asm = "loop: addi x1, x1, 0\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "loop:"

    def test_no_fusion_across_inline_label(self):
        """A target on the second instruction is a block boundary."""
        asm = "  addi x1, x1, 3\nloop: addi x1, x1, 5\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Multi-rule interaction
# ---------------------------------------------------------------------------


class TestMultiRule:
    """Multiple rules firing in a single pass."""

    def test_multiple_rules_fire(self):
        """All three rules should fire in sequence."""
        asm = (
            "  addi x1, x1, 3\n"
            "  addi x1, x1, 5\n"
            "  li x2, 10\n"
            "  addi x2, x2, 7\n"
            "  beq x0, x0, done\n"
        )
        lines = parse_asm(asm)
        result, changes, rule_matches = peephole_pass(lines, RULES)
        assert changes >= 3
        assert rule_matches["addi+addi fusion"] >= 1
        assert rule_matches["li+addi fusion"] >= 1
        assert rule_matches["beq zero-zero to j"] >= 1

    def test_no_changes_on_optimal(self):
        """Already optimal code → zero changes."""
        asm = "  addi x1, x2, 3\n  nop\n  ret\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Rule 4: mv swap elimination
# ---------------------------------------------------------------------------


class TestMvSwap:
    """mv x,y; mv y,x → keep the first copy and delete the redundant second."""

    def test_mv_swap(self):
        """The reverse copy is redundant after the first copy."""
        asm = "  mv t0, t1\n  mv t1, t0\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "  mv t0, t1"

    def test_no_swap_diff_regs(self):
        """mv x,y; mv x,z (different registers) → no match."""
        asm = "  mv t0, t1\n  mv t0, t2\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_zero_destination_is_not_optimized(self):
        """Writing x0 does not establish the value used by the second move."""
        asm = "  mv zero, t0\n  mv t0, zero\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Rule 5: mv chain shortening
# ---------------------------------------------------------------------------


class TestMvChain:
    """Keep mv a,b and rewrite dependent mv c,a → mv c,b."""

    def test_mv_chain(self):
        """The first assignment stays live while the dependency is shortened."""
        asm = "  mv t0, t1\n  mv t2, t0\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert lines_to_asm(result) == "  mv t0, t1\n  mv t2, t1"

    def test_no_chain_independent(self):
        """mv a,b; mv c,d (no data dep) → no match."""
        asm = "  mv t0, t1\n  mv t3, t4\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_zero_destination_is_not_forwarded(self):
        """A write to x0 cannot feed the following move."""
        asm = "  mv zero, t0\n  mv t1, zero\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0


# ---------------------------------------------------------------------------
# Rule 6: addi zero elimination
# ---------------------------------------------------------------------------


class TestAddiZero:
    """addi rd, rd, 0 is a no-op and may be deleted."""

    def test_addi_zero(self):
        """Adding zero to the same register is redundant."""
        asm = "  addi x1, x1, 0\n"
        lines = parse_asm(asm)
        result, changes, _ = peephole_pass(lines, RULES)
        assert changes == 1
        assert "addi" not in lines_to_asm(result)

    def test_addi_copy_not_deleted(self):
        """addi rd, rs, 0 copies rs when the registers differ."""
        asm = "  addi x1, x2, 0\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0

    def test_addi_nonzero_not_deleted(self):
        """addi rd, rd, non-zero → kept."""
        asm = "  addi x1, x1, 5\n"
        lines = parse_asm(asm)
        _, changes, _ = peephole_pass(lines, RULES)
        assert changes == 0
