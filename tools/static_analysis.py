"""Dependency-free security-focused Python static checks."""

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable


@dataclass(frozen=True)
class Issue:
    path: str
    line: int
    code: str


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.issues: list[Issue] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module and node.module.split(".", 1)[0] not in sys.stdlib_module_names | {"hermodr", "tools", "tests", "hermodr_build_backend"}:
            self.issues.append(Issue(self.path, node.lineno, "external_dependency"))
        if any(alias.name == "*" for alias in node.names):
            self.issues.append(Issue(self.path, node.lineno, "wildcard_import"))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        allowed = sys.stdlib_module_names | {"hermodr", "tools", "tests", "hermodr_build_backend"}
        if any(alias.name.split(".", 1)[0] not in allowed for alias in node.names):
            self.issues.append(Issue(self.path, node.lineno, "external_dependency"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            self.issues.append(Issue(self.path, node.lineno, "dynamic_execution"))
        if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords):
            self.issues.append(Issue(self.path, node.lineno, "shell_execution"))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.issues.append(Issue(self.path, node.lineno, "bare_exception"))
        self.generic_visit(node)


def analyze_source(source: str, path: str = "<memory>") -> tuple[Issue, ...]:
    visitor = _Visitor(path)
    visitor.visit(ast.parse(source, filename=path))
    return tuple(visitor.issues)


def python_files(paths: Iterable[Path]) -> tuple[Path, ...]:
    files = []
    for path in paths:
        files.extend(path.rglob("*.py") if path.is_dir() else (path,))
    return tuple(sorted(set(files)))


def run(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="static-analysis")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(arguments)
    issues = []
    for path in python_files(args.paths):
        issues.extend(analyze_source(path.read_text(encoding="utf-8"), str(path)))
    for issue in issues:
        print(f"{issue.path}:{issue.line}: {issue.code}")
    return 1 if issues else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
