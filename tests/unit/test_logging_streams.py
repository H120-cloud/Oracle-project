"""Log records must be split by stream: INFO/DEBUG → stdout, WARNING+ → stderr.

`logging.basicConfig` defaults to stderr, so container log collectors (Railway)
flag every INFO line as `severity: error`. Routing normal logs to stdout fixes
the false-error noise while keeping real warnings/errors on stderr.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_info_logs_to_stdout_and_warnings_to_stderr():
    code = (
        "import logging, src.main; "
        "logging.getLogger('oracle').info('INFO_MARKER_XYZ'); "
        "logging.getLogger('oracle').warning('WARN_MARKER_XYZ')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=180,
    )

    assert "INFO_MARKER_XYZ" in result.stdout
    assert "INFO_MARKER_XYZ" not in result.stderr
    assert "WARN_MARKER_XYZ" in result.stderr
    assert "WARN_MARKER_XYZ" not in result.stdout
