"""Architecture import rules (AST, nothing imported) + app smoke tests.

Layer rules enforced on every project .py file:
- frontend/ must not import requests, sqlite3, database, backend.repositories
  or backend.integrations (services and config only).
- backend/services/ must not import sqlite3, requests or database.
- Only database/ and backend/repositories/ may import database
  (tests/ are exempt: they verify the layers directly).
- Only backend/integrations/, extras/ and scripts/ may import requests.
- No module may import the deleted src package.
"""

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "frontend" / "app.py"

_EXCLUDED_PARTS = (".venv", ".git", "__pycache__", ".pytest_cache")


def _iter_py_files():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in _EXCLUDED_PARTS for part in rel.split("/")):
            continue
        yield rel, path


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names from Import/ImportFrom nodes in one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def _scan():
    """Map relative path -> imported modules for every project .py file."""
    return {rel: _imported_modules(path) for rel, path in _iter_py_files()}


def _is_within(mod: str, package: str) -> bool:
    return mod == package or mod.startswith(package + ".")


def test_frontend_imports_only_services_config_and_frontend():
    offenders = []
    for rel, modules in _scan().items():
        if not rel.startswith("frontend/"):
            continue
        for mod in sorted(modules):
            if mod.split(".")[0] in {"requests", "sqlite3", "database"}:
                offenders.append(f"{rel} imports {mod}")
            elif _is_within(mod, "backend.repositories") or _is_within(
                mod, "backend.integrations"
            ):
                offenders.append(f"{rel} imports {mod}")
    assert offenders == []


def test_services_import_no_db_or_http():
    offenders = []
    for rel, modules in _scan().items():
        if not rel.startswith("backend/services/"):
            continue
        for mod in sorted(modules):
            if mod.split(".")[0] in {"sqlite3", "requests", "database"}:
                offenders.append(f"{rel} imports {mod}")
    assert offenders == []


def test_only_repositories_and_database_import_database():
    offenders = []
    for rel, modules in _scan().items():
        if rel.startswith(("database/", "backend/repositories/", "tests/")):
            continue
        for mod in sorted(modules):
            if _is_within(mod, "database"):
                offenders.append(f"{rel} imports {mod}")
    assert offenders == []


def test_only_integrations_extras_scripts_import_requests():
    offenders = []
    for rel, modules in _scan().items():
        if rel.startswith(("backend/integrations/", "extras/", "scripts/")):
            continue
        for mod in sorted(modules):
            if _is_within(mod, "requests"):
                offenders.append(f"{rel} imports {mod}")
    assert offenders == []


def test_no_src_imports_anywhere():
    offenders = []
    for rel, modules in _scan().items():
        for mod in sorted(modules):
            if _is_within(mod, "src"):
                offenders.append(f"{rel} imports {mod}")
    assert offenders == []


def test_app_entry_stays_small():
    line_count = len(APP_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count < 200


def test_app_loads_without_exception():
    app = AppTest.from_file(str(APP_PATH))
    app.run()
    assert not app.exception


@pytest.mark.parametrize("step", ["upload", "transcribe", "review", "export"])
def test_view_empty_state_renders(step):
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["current_step"] = step
    app.run()
    assert not app.exception
