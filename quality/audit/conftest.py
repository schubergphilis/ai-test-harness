import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import registry  # noqa: E402  (harnesses.toml)

PURPOSE = os.environ.get("AUDIT_PURPOSE", "audit")  # port range: harnesses.toml [ports]


def selected_harnesses() -> list[str]:
    only = [h for h in os.environ.get("AUDIT_HARNESSES", "").split(",") if h]
    return only or registry.names()


def pytest_generate_tests(metafunc):
    if "harness" in metafunc.fixturenames:
        metafunc.parametrize("harness", selected_harnesses())


@pytest.fixture
def target_url(harness):
    return f"http://localhost:{registry.port(harness, PURPOSE)}"


@pytest.fixture(scope="session")
def trace_file():
    return os.environ.get("TRACE_FILE", os.path.join(os.path.dirname(__file__), "results", "traces-mock.jsonl"))
