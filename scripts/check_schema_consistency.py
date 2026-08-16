#!/usr/bin/env python3
"""Verificacao estatica: models x migration inicial, sem instalar nada.

A migration inicial e escrita a mao, entao models e schema poderiam divergir em
silencio. `tests/integration/test_migrations.py` pega isso em tempo de execucao;
este script pega antes, por AST, e roda com Python puro — util em pre-commit e
em ambiente sem dependencias instaladas.

Uso::

    python3 scripts/check_schema_consistency.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "src" / "copilot" / "db" / "models"
MIGRATIONS_DIR = ROOT / "migrations" / "versions"
BASELINE = MIGRATIONS_DIR / "0001_initial_schema.py"

#: Colunas herdadas dos mixins de `copilot.db.base`.
MIXIN_COLUMNS = {
    "DomainBase": {"id", "created_at", "dataset_kind"},
    "AsOfDomainBase": {"id", "created_at", "dataset_kind", "as_of"},
}

#: Helpers da migration que expandem para uma coluna.
MIGRATION_HELPERS = {
    "_id": "id",
    "_created": "created_at",
    "_dataset_kind": "dataset_kind",
    "_as_of": "as_of",
}


def model_tables() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for path in sorted(MODELS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            table_name: str | None = None
            columns: set[str] = set()
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__":
                            table_name = stmt.value.value  # type: ignore[attr-defined]
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    value = stmt.value
                    if (
                        isinstance(value, ast.Call)
                        and getattr(value.func, "id", "") == "mapped_column"
                    ):
                        columns.add(stmt.target.id)
            if table_name:
                for base in bases:
                    columns |= MIXIN_COLUMNS.get(base, set())
                if "TimestampMixin" in bases:
                    columns.add("created_at")
                tables[table_name] = columns
    return tables


def migration_tables() -> tuple[dict[str, set[str]], list[str]]:
    tables: dict[str, set[str]] = {}
    order: list[str] = []
    for arquivo in sorted(MIGRATIONS_DIR.glob("*.py")):
        _scan(ast.parse(arquivo.read_text(encoding="utf-8")), tables, order)
    return tables, order


def _scan(tree: ast.AST, tables: dict[str, set[str]], order: list[str]) -> None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
        ):
            name = node.args[0].value  # type: ignore[attr-defined]
            order.append(name)
            columns: set[str] = set()
            for arg in node.args[1:]:
                if not isinstance(arg, ast.Call):
                    continue
                fn = arg.func
                fname = getattr(fn, "attr", getattr(fn, "id", ""))
                if fname == "Column":
                    columns.add(arg.args[0].value)  # type: ignore[attr-defined]
                elif fname in MIGRATION_HELPERS:
                    columns.add(MIGRATION_HELPERS[fname])
            tables[name] = columns


def declared_order() -> list[str]:
    tree = ast.parse((MODELS_DIR / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TABLE_CREATE_ORDER":
            return [e.value for e in node.value.elts]  # type: ignore[attr-defined,union-attr]
    return []


def drop_order() -> list[str]:
    tree = ast.parse(BASELINE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Tuple):
                    return [e.value for e in sub.elts if isinstance(e, ast.Constant)]
    return []


def main() -> int:
    models = model_tables()
    migration, create_order = migration_tables()
    problems: list[str] = []

    if set(models) != set(migration):
        problems.append(
            "tabelas divergentes: "
            f"so nos models={sorted(set(models) - set(migration))} "
            f"so na migration={sorted(set(migration) - set(models))}"
        )

    for table in sorted(set(models) & set(migration)):
        if models[table] != migration[table]:
            problems.append(
                f"{table}: model-only={sorted(models[table] - migration[table])} "
                f"migration-only={sorted(migration[table] - models[table])}"
            )

    declared = declared_order()
    if set(declared) != set(create_order):
        problems.append(
            "TABLE_CREATE_ORDER diverge das migrations: "
            f"so no init={sorted(set(declared) - set(create_order))} "
            f"so nas migrations={sorted(set(create_order) - set(declared))}"
        )

    # A ordem de drop precisa ser o inverso exato da criacao da baseline (0001).
    baseline: dict[str, set[str]] = {}
    baseline_order: list[str] = []
    _scan(ast.parse(BASELINE.read_text(encoding="utf-8")), baseline, baseline_order)
    if (drops := drop_order()) and drops != list(reversed(baseline_order)):
        problems.append(f"ordem de drop nao e o inverso da criacao\n  drop={drops}")

    print(f"tabelas nos models   : {len(models)}")
    print(f"tabelas na migration : {len(migration)}")
    print(f"colunas mapeadas     : {sum(len(v) for v in models.values())}")

    if problems:
        print("\nPROBLEMAS:")
        for problem in problems:
            print(" -", problem)
        return 1

    print("\nOK: models, migration, TABLE_CREATE_ORDER e ordem de drop consistentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
