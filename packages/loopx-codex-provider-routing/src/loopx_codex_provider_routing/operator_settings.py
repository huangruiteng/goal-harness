"""Private, explicit local targets for the opt-in CPA operator CLI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit


class OperatorSettings:
    PATH_KEYS: ClassVar[set[str]] = {
        "runtime_root",
        "temporary_root",
        "binary",
        "plugin_directory",
        "codex_binary",
        "gpt_cache",
        "astra_cache",
        "ark_catalog",
        "ark_profile_catalog",
        "ark_env_file",
    }
    OPTIONAL_PATH_KEYS: ClassVar[set[str]] = {"login_source"}
    VALUE_KEYS: ClassVar[set[str]] = {
        "schema_version",
        "paths",
        "binary_sha256",
        "plugin_sha256",
        "source_commit",
        "port",
        "launchd_label",
        "ark_base_url",
        "ark_model",
        "ark_pro_model",
    }

    def __init__(self, data: dict):
        if (
            set(data) != self.VALUE_KEYS
            or data["schema_version"] != "loopx_cpa_local_operator_v1"
        ):
            raise ValueError("local configuration has missing or unsupported fields")
        paths = data["paths"]
        if (
            not isinstance(paths, dict)
            or not self.PATH_KEYS <= paths.keys()
            or set(paths) - self.PATH_KEYS - self.OPTIONAL_PATH_KEYS
        ):
            raise ValueError("local configuration requires explicit path references")
        self.paths = {}
        for key, raw in paths.items():
            if not isinstance(raw, str) or not Path(raw).is_absolute():
                raise ValueError(f"{key} requires an absolute local path")
            path = Path(raw)
            if path.is_symlink():
                raise ValueError(f"{key} must not be a symbolic link")
            self.paths[key] = path.resolve()
        for key in ("runtime_root", "temporary_root"):
            target = self.paths[key]
            if target == Path(target.anchor) or target == Path.home():
                raise ValueError(f"{key} must be a dedicated directory")
            if any((parent / ".git").exists() for parent in (target, *target.parents)):
                raise ValueError(f"{key} must be outside Git worktrees")
        if self.paths["runtime_root"] == self.paths["temporary_root"]:
            raise ValueError("runtime and temporary roots must differ")
        for key in ("binary_sha256", "plugin_sha256"):
            if (
                not isinstance(data[key], str)
                or re.fullmatch(r"[0-9a-f]{64}", data[key]) is None
            ):
                raise ValueError(f"{key} must be an exact SHA-256")
        if (
            not isinstance(data["source_commit"], str)
            or re.fullmatch(r"[0-9a-f]{40}", data["source_commit"]) is None
        ):
            raise ValueError("source_commit must be an exact Git commit")
        if type(data["port"]) is not int or not 1024 <= data["port"] <= 65535:
            raise ValueError("port must be an unprivileged TCP port")
        if (
            not isinstance(data["launchd_label"], str)
            or re.fullmatch(r"[A-Za-z0-9._-]+", data["launchd_label"]) is None
        ):
            raise ValueError("launchd_label must be a service identifier")
        url = urlsplit(data["ark_base_url"])
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("fallback endpoint must be credential-free HTTPS")
        for key in ("ark_model", "ark_pro_model"):
            if (
                not isinstance(data[key], str)
                or re.fullmatch(r"[a-z0-9._-]+", data[key]) is None
            ):
                raise ValueError(f"{key} must be a model identifier")
        self.data = data

    @classmethod
    def read(cls, path: Path):
        if not path.is_absolute() or path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError(
                "operator config requires a private regular file (mode 0600)"
            )
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def runtime_attributes(self):
        p, d = self.paths, self.data
        root, temporary = p["runtime_root"], p["temporary_root"]
        state, logs = root / "state", root / "logs"
        return {
            "SOURCE_COMMIT": d["source_commit"],
            "BINARY_SHA256": d["binary_sha256"],
            "BINARY": p["binary"],
            "PLUGIN_DIR": p["plugin_directory"],
            "FAST_SELECTOR_PLUGIN": p["plugin_directory"] / "fast-selector-tier.dylib",
            "FAST_SELECTOR_PLUGIN_SHA256": d["plugin_sha256"],
            "RUNTIME_ROOT": root,
            "AUTH_DIR": root / "auth",
            "STATE_DIR": state,
            "LOG_DIR": logs,
            "MODEL_CATALOG": root / "codex-model-catalog.json",
            "PID_FILE": state / "cpa.pid",
            "SLOTS_FILE": state / "oauth-slots.json",
            "MANAGEMENT_KEY_FILE": state / "management.key",
            "STATUS_SNAPSHOT_FILE": state / "route-status.json",
            "RUNTIME_TMP_ROOT": temporary,
            "RUNTIME_CONFIG": temporary / "runtime-config.yaml",
            "PORT": d["port"],
            "LAUNCHD_LABEL": d["launchd_label"],
            "ARK_BASE_URL": d["ark_base_url"],
            "ARK_MODEL": d["ark_model"],
            "ARK_PRO_MODEL": d["ark_pro_model"],
            "ARK_LEGACY_MODELS": ("deepseek-v4-flash", d["ark_model"]),
            "LOG_CANDIDATES": (logs / "launchd.log", logs / "cpa.log"),
        }
