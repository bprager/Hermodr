"""Strict coverage gate for Python's standard-library trace reports."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path


_COVERED_LINE = re.compile(r"^\s+[0-9]+:")
_MISSING_LINE = re.compile(r"^>>>>>> ")


class CoverageFailure(RuntimeError):
    """Raised when coverage evidence is missing or below the threshold."""


def count_lines(lines: Iterable[str]) -> tuple[int, int]:
    """Count covered and missed executable lines in trace output."""

    covered = 0
    missed = 0
    for line in lines:
        if _COVERED_LINE.match(line):
            covered += 1
        elif _MISSING_LINE.match(line):
            missed += 1
    return covered, missed


def enforce(covered: int, missed: int, threshold: float = 95.0) -> float:
    """Return coverage percent or fail when it is not strictly above threshold."""

    total = covered + missed
    if total == 0:
        raise CoverageFailure("no executable coverage lines found")
    percentage = 100.0 * covered / total
    if percentage <= threshold:
        raise CoverageFailure(
            f"coverage {percentage:.2f}% ({covered}/{total}) must be greater than {threshold:.2f}%"
        )
    return percentage


def main(arguments: Sequence[str]) -> int:
    """Evaluate one or more trace cover files and print aggregate evidence."""

    covered = 0
    missed = 0
    for argument in arguments:
        with Path(argument).open(encoding="utf-8") as report:
            report_covered, report_missed = count_lines(report)
        covered += report_covered
        missed += report_missed
    percentage = enforce(covered, missed)
    print(f"Hermodr line coverage: {percentage:.2f}% ({covered}/{covered + missed})")
    return 0
