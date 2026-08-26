"""Static verification of the layers that cannot be executed here.

Why this exists: `app/core/errors.py` shipped importing a `DomainError`
subclass name that never existed. Nothing caught it, because that module is
imported only by the FastAPI layer, and the FastAPI layer has never been run in
an environment without third-party packages installed. A whole tier of the
application was therefore unverified by anything at all.

This script parses every module with `ast` and never imports one, so it can
verify FastAPI, SQLAlchemy and Alembic modules with none of those packages
present. It checks three things:

1. **Resolvable imports.** Every `from app.x import y` names something that
   actually exists in `app.x`.
2. **Architectural boundaries.** No reasoning, detection or policy module can
   reach a payment provider, and the domain has no outward dependencies. This
   is the central safety claim of the system; `import-linter` enforces it in CI
   but requires an install, and this claim is too important to be verifiable
   only when the network is available.
3. **Money hygiene.** No float arithmetic or float literals in modules that
   handle amounts.

Exit code is non-zero if anything fails.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# app.agents/detection/policies propose and decide. None of them may touch a
# provider. app.services.executor is the only component permitted to.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "app.agents": ("app.integrations.razorpay", "app.integrations.mock_razorpay"),
    "app.detection": ("app.integrations.razorpay", "app.integrations.mock_razorpay"),
    "app.policies": ("app.integrations.razorpay", "app.integrations.mock_razorpay"),
    "app.domain": (
        "app.api",
        "app.services",
        "app.agents",
        "app.integrations",
        "app.repositories",
        "app.models",
        "app.policies",
        "app.detection",
        "app.webhooks",
        "fastapi",
        "sqlalchemy",
        "redis",
    ),
    "app.core": ("app.services", "app.agents", "app.api", "app.repositories"),
}

# Modules where a float would be a defect rather than a nuisance.
MONEY_SENSITIVE = ("app/domain/money.py", "app/services/executor.py")


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def iter_modules() -> list[tuple[str, pathlib.Path, ast.Module]]:
    found = []
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            print(f"FAIL syntax  {path.relative_to(ROOT)}: {exc}")
            raise SystemExit(1) from exc
        found.append((module_name(path), path, tree))
    return found


def exported_names(tree: ast.Module) -> set[str]:
    """Top-level names a module makes available to `from x import y`."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.If | ast.Try):
            # Conditional definitions, e.g. TYPE_CHECKING blocks.
            for sub in ast.walk(node):
                if isinstance(sub, ast.ClassDef | ast.FunctionDef):
                    names.add(sub.name)
                elif isinstance(sub, ast.ImportFrom):
                    for alias in sub.names:
                        names.add(alias.asname or alias.name)
    return names


def check_imports(modules) -> list[str]:
    known = {name: exported_names(tree) for name, _, tree in modules}
    failures: list[str] = []

    for name, path, tree in modules:
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("app.") and node.module != "app":
                continue

            target = node.module
            if target not in known:
                failures.append(
                    f"{rel}:{node.lineno} imports from unknown module {target!r}"
                )
                continue

            for alias in node.names:
                if alias.name == "*":
                    failures.append(
                        f"{rel}:{node.lineno} uses `import *` from {target!r}"
                    )
                    continue
                # Importing a submodule is legitimate.
                if f"{target}.{alias.name}" in known:
                    continue
                if alias.name not in known[target]:
                    failures.append(
                        f"{rel}:{node.lineno} imports {alias.name!r} from "
                        f"{target!r}, which does not define it"
                    )
        _ = name
    return failures


def check_boundaries(modules) -> list[str]:
    failures: list[str] = []
    for name, path, tree in modules:
        rel = path.relative_to(ROOT)
        for layer, banned in FORBIDDEN.items():
            if not (name == layer or name.startswith(layer + ".")):
                continue
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    targets.append(node.module)
                elif isinstance(node, ast.Import):
                    targets.extend(a.name for a in node.names)
                for target in targets:
                    for bad in banned:
                        if target == bad or target.startswith(bad + "."):
                            failures.append(
                                f"{rel}:{node.lineno} {layer} must not import "
                                f"{target} (boundary violation)"
                            )
    return failures


def check_money(modules) -> list[str]:
    failures: list[str] = []
    for _, path, tree in modules:
        rel = str(path.relative_to(ROOT))
        if not any(rel.endswith(s) for s in MONEY_SENSITIVE):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                failures.append(
                    f"{rel}:{node.lineno} float literal {node.value!r} in a "
                    "money-handling module"
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                failures.append(
                    f"{rel}:{node.lineno} float() cast in a money-handling "
                    "module; convert via Decimal(str(x)) instead"
                )
    return failures


def main() -> int:
    modules = iter_modules()
    print(f"parsed {len(modules)} modules without importing any of them\n")

    sections = [
        ("resolvable imports", check_imports(modules)),
        ("architectural boundaries", check_boundaries(modules)),
        ("money hygiene", check_money(modules)),
    ]

    total = 0
    for label, failures in sections:
        if failures:
            total += len(failures)
            print(f"FAIL  {label} ({len(failures)})")
            for failure in failures:
                print(f"        {failure}")
        else:
            print(f"ok    {label}")

    if total:
        print(f"\nstatic check FAILED with {total} problem(s)")
        return 1

    print("\nstatic check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
