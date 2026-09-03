#!/usr/bin/env python3
"""Keep installed Dashboard quick starts on the single-process contract."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE_URL = "http://127.0.0.1:8767/chat/"
DEFAULT_STATUS_URL = "http://127.0.0.1:8767/status.json"


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def compact(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    documents = {
        "getting started": read("docs/guides/getting-started.md"),
        "dashboard README": read("apps/presentation/dashboard/README.md"),
        "workspace guide": read("docs/guides/personal-workspace-user-guide.md"),
    }

    for label, content in documents.items():
        normalized = compact(content)
        assert "loopx dashboard" in normalized, label
        assert "--no-open" in normalized, label
        assert DEFAULT_WORKSPACE_URL in normalized, label
        assert DEFAULT_STATUS_URL in normalized, label

    installed_run = compact(
        documents["dashboard README"].split("## Run", 1)[1].split(
            "Source-checkout development is a separate mode:", 1
        )[0]
    )
    assert "does not require a separate `loopx serve-status` process" in installed_run
    assert "127.0.0.1:5173" not in installed_run
    assert "installs the dashboard's npm dependencies" not in installed_run

    print("dashboard-installed-quickstart-doc-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
