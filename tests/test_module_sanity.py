"""Import-sanity safety net.

Every Python module under the source roots must import without raising. This
catches the entire class of bug that ordinary unit tests miss: a module that
crashes at *import time* — a missing dependency, an undefined name in an
evaluated annotation, a typo'd symbol, a bad relative import — even when no test
exercises that file's logic.

It is intentionally dumb and exhaustive: discover every module, attempt to
import each one in its own parametrized case, and let any exception fail loudly
with the offending module named in the test id. If it imports, it passes.

Adding a new source package? Extend ``SOURCE_DIRS``.
"""

import importlib
from pathlib import Path

import pytest

# Source roots whose every module must be importable. Kept narrow on purpose:
# these are the package trees we ship/run. CLI scripts under scripts/ are not
# included because they may run side-effecting code at import.
SOURCE_DIRS = ("src",)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _discover_modules():
    """Return dotted module names for every .py file under SOURCE_DIRS."""
    modules = []
    for src_dir in SOURCE_DIRS:
        base = _REPO_ROOT / src_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(_REPO_ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                modules.append(".".join(parts))
    return modules


MODULES = _discover_modules()


def test_module_discovery_is_not_empty():
    """Guard against a silently-empty parametrization.

    If discovery breaks (wrong CWD, layout change), the parametrized import test
    would collect zero cases and pass vacuously — defeating the safety net. This
    fails instead.
    """
    assert MODULES, "No modules discovered under SOURCE_DIRS — import net is inert."


@pytest.mark.parametrize("module_name", MODULES, ids=MODULES)
def test_module_imports_cleanly(module_name):
    """Importing the module must not raise."""
    importlib.import_module(module_name)
