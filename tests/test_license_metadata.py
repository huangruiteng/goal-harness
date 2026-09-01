from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APACHE_2_LICENSE_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
)


def _project_metadata(path: str) -> dict[str, object]:
    data = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
    project = data.get("project")
    assert isinstance(project, dict)
    return project


def test_root_license_is_canonical_apache_2_with_historical_notices() -> None:
    license_bytes = (ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == APACHE_2_LICENSE_SHA256

    historical_mit = (ROOT / "LICENSE-MIT").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert historical_mit.startswith("MIT License\n\nCopyright (c) 2026 LoopX contributors")
    assert "releases through v0.4.7 were distributed under the MIT License" in notice


def test_python_distributions_declare_apache_2() -> None:
    root_project = _project_metadata("pyproject.toml")
    assert root_project["version"] == "0.5.3"
    assert '__version__ = "0.5.3"' in (ROOT / "loopx/__init__.py").read_text()
    assert root_project["license"] == "Apache-2.0"
    assert set(root_project["license-files"]) == {"LICENSE", "NOTICE", "LICENSE-MIT"}

    extension_project = _project_metadata(
        "packages/loopx-finance-value-discovery/pyproject.toml"
    )
    assert extension_project["license"] == "Apache-2.0"


def test_npm_workspace_metadata_declares_apache_2() -> None:
    for package_dir in ("apps/presentation/site", "apps/presentation/dashboard"):
        manifest = json.loads((ROOT / package_dir / "package.json").read_text())
        lock = json.loads((ROOT / package_dir / "package-lock.json").read_text())
        assert manifest["license"] == "Apache-2.0"
        assert lock["packages"][""]["license"] == "Apache-2.0"


def test_public_docs_state_the_versioned_transition() -> None:
    licensing = (ROOT / "docs/project/licensing.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "beginning with `v0.4.8`" in licensing
    assert "through `v0.4.7`" in licensing
    assert "git commit -s" in contributing
    assert (ROOT / "DCO").read_text(encoding="utf-8").startswith(
        "Developer Certificate of Origin\nVersion 1.1"
    )
