"""Opt-in local operator; deliberately separate from the read-only extension API."""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import secrets
import sys
from pathlib import Path

from .operator_catalog import AppCatalog
from .operator_runtime import CPAOperator, sha256, write_private
from .operator_settings import OperatorSettings
from .selectors import SLOTS

COMMANDS = (
    "prepare",
    "reconcile",
    "write-catalog",
    "probe",
    "validate",
    "status",
    "route-status",
    "start",
    "serve",
    "stop",
    "enroll",
    "snapshot",
    "rollback",
    "reset-cooldown",
)


def snapshot(runtime: CPAOperator) -> str:
    """Snapshot only the fixed catalog and registered credentials, never task stores."""
    snapshot_id = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ-"
    ) + secrets.token_hex(4)
    directory = runtime.STATE_DIR / "operator-backups" / snapshot_id
    directory.mkdir(parents=True, mode=0o700)
    targets = [runtime.SLOTS_FILE, runtime.MODEL_CATALOG]
    targets += [runtime.AUTH_DIR / name for name in runtime.load_slots().values()]
    entries = []
    for index, target in enumerate(targets):
        if not target.exists():
            continue
        relative = str(target.relative_to(runtime.RUNTIME_ROOT))
        content = target.read_text(encoding="utf-8")
        saved = directory / f"{index}.json"
        write_private(saved, content)
        entries.append(
            {"target": relative, "backup": saved.name, "sha256": sha256(saved)}
        )
    write_private(directory / "manifest.json", json.dumps({"files": entries}))
    return snapshot_id


def rollback(runtime: CPAOperator, snapshot_id: str) -> None:
    if (
        not snapshot_id
        or Path(snapshot_id).name != snapshot_id
        or snapshot_id in {".", ".."}
    ):
        raise ValueError("rollback requires a snapshot identifier")
    directory = runtime.STATE_DIR / "operator-backups" / snapshot_id
    if directory.is_symlink() or (directory / "manifest.json").is_symlink():
        raise ValueError("snapshot must not be a symbolic link")
    entries = json.loads((directory / "manifest.json").read_text())["files"]
    allowed = {"state/oauth-slots.json", "codex-model-catalog.json"}
    prepared = []
    for entry in entries:
        relative, name = entry["target"], entry["backup"]
        parts = Path(relative).parts
        if relative not in allowed and not (
            len(parts) == 2 and parts[0] == "auth" and parts[1].endswith(".json")
        ):
            raise ValueError("snapshot target is outside the operator allowlist")
        if Path(name).name != name:
            raise ValueError("invalid backup member")
        source, target = directory / name, runtime.RUNTIME_ROOT / relative
        if (
            source.is_symlink()
            or target.is_symlink()
            or sha256(source) != entry["sha256"]
        ):
            raise ValueError("snapshot integrity check failed")
        prepared.append((target, source.read_text()))
    # OAuth refresh tokens rotate. Restore routing metadata onto the newest
    # credential, never roll a live credential back to a stale refresh token.
    restored = []
    previous_slots = None
    for target, content in prepared:
        if target == runtime.SLOTS_FILE:
            previous_slots = json.loads(content)
        if target.parent == runtime.AUTH_DIR and target.exists():
            current = json.loads(target.read_text())
            old = json.loads(content)
            if current.get("account_id") != old.get("account_id"):
                raise ValueError("credential identity changed since snapshot")
            for field in (
                "priority",
                "request_retry",
                "disable_cooling",
                "websockets",
                "loopx_slot",
                "model_aliases",
            ):
                if field in old:
                    current[field] = old[field]
                else:
                    current.pop(field, None)
            content = json.dumps(current, separators=(",", ":"))
        restored.append((target, content))
    # Enrollment rollback preserves the newly saved credential, but removes it
    # from the live router so file discovery cannot bypass the restored slots.
    if previous_slots is not None:
        for slot, name in runtime.load_slots().items():
            if name not in previous_slots.values():
                path = runtime.AUTH_DIR / name
                if path.is_file():
                    data = json.loads(path.read_text())
                    if data.get("loopx_slot") != slot:
                        raise ValueError(
                            "new credential no longer belongs to this slot"
                        )
                    data.update(disabled=True, model_aliases=[])
                    restored.append((path, json.dumps(data, separators=(",", ":"))))
    for target, content in restored:
        write_private(target, content)


def enroll(runtime: CPAOperator, slot: str) -> None:
    source = runtime.settings.paths.get("login_source")
    if source is None:
        raise ValueError("enrollment requires an explicit login_source reference")
    slots = runtime.load_slots()
    if slot in slots:
        raise ValueError("slot already enrolled; existing credentials were retained")
    auth = json.loads(source.read_text())
    tokens = auth.get("tokens", {})
    if auth.get("auth_mode") != "chatgpt" or any(
        not isinstance(tokens.get(k), str) or not tokens[k]
        for k in ("access_token", "id_token", "refresh_token", "account_id")
    ):
        raise ValueError("source is not a complete ChatGPT login")

    def claims(token):
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))

    identity, access = claims(tokens["id_token"]), claims(tokens["access_token"])
    account = identity.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
    if (
        account != tokens["account_id"]
        or access.get("exp", 0) <= dt.datetime.now(dt.timezone.utc).timestamp()
    ):
        raise ValueError(
            "login identity mismatch or expired access token; refresh the source login"
        )
    for name in slots.values():
        if (
            json.loads((runtime.AUTH_DIR / name).read_text()).get("account_id")
            == account
        ):
            raise ValueError("this account is already enrolled in another slot")
    target = runtime.AUTH_DIR / (
        "codex-" + hashlib.sha256(account.encode()).hexdigest()[:16] + ".json"
    )
    if target.exists():
        raise ValueError("credential target already exists")
    record = {
        k: tokens[k]
        for k in ("access_token", "id_token", "refresh_token", "account_id")
    }
    record.update(
        type="codex",
        email=identity.get("email", ""),
        disabled=False,
        expired=dt.datetime.fromtimestamp(access["exp"], dt.timezone.utc).isoformat(),
        last_refresh=auth.get("last_refresh"),
    )
    write_private(target, json.dumps(record, separators=(",", ":")))
    runtime.patch_slot_auth(target, slot)
    slots[slot] = target.name
    write_private(runtime.SLOTS_FILE, json.dumps(slots, separators=(",", ":")))


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loopx-cpa-operator")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="authorize this exact local command; otherwise only emit a plan",
    )
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--slot", choices=SLOTS)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--modality", choices=("text", "image"), default="text")
    parser.add_argument("--fast", action="store_true")
    args = parser.parse_args(argv)
    settings = OperatorSettings.read(args.config)
    if args.command in {"enroll", "reset-cooldown"} and not args.slot:
        raise ValueError(f"{args.command} requires --slot")
    if args.command == "rollback" and not args.snapshot_id:
        raise ValueError("rollback requires --snapshot-id")
    receipt = {
        "schema_version": "loopx_cpa_operator_receipt_v1",
        "command": args.command,
        "executed": args.execute,
        "credential_free": True,
    }
    if not args.execute:
        receipt.update(
            effect_boundary="explicit_local_operator",
            task_store_effects="none",
            targets="configured_paths_only",
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    runtime = CPAOperator(settings)
    runtime.check_target_boundaries()
    catalog = AppCatalog(runtime)
    if args.command in {"reconcile", "write-catalog", "enroll"}:
        receipt["rollback_snapshot"] = snapshot(runtime)
    captured = io.StringIO()
    # Diagnostics can contain local paths. Public receipts return only typed,
    # symbolic results; raw management data and subprocess output stay local.
    with contextlib.redirect_stdout(captured):
        if args.command == "write-catalog":
            catalog.write_catalog()
            receipt["model_count"] = len(catalog.generate_catalog()["models"])
        elif args.command == "probe":
            result = catalog.probe()
            receipt["passed"] = result["passed"]
            receipt["model_count"] = len(result["projected_selectors"])
            receipt["visible_selectors"] = result["visible_selectors"]
            receipt["checks"] = {
                k: result[k]
                for k in (
                    "missing",
                    "unexpected_visible",
                    "hidden",
                    "cpa_missing",
                    "route_mismatches",
                    "wrong_default_service_tiers",
                )
            }
        elif args.command == "enroll":
            runtime.prepare()
            enroll(runtime, args.slot)
            receipt["enrolled_slot"] = args.slot
        elif args.command == "reset-cooldown":
            receipt["recovery"] = runtime.reset_cooldown(args.slot)
        elif args.command == "snapshot":
            receipt["rollback_snapshot"] = snapshot(runtime)
        elif args.command == "rollback":
            rollback(runtime, args.snapshot_id)
        elif args.command in {"start", "serve"}:
            getattr(runtime, args.command)(settings.paths["ark_env_file"])
        elif args.command == "route-status":
            runtime.route_status(modality=args.modality, fast=args.fast)
            receipt["observation"] = json.loads(captured.getvalue())
        elif args.command == "status":
            receipt["running"] = runtime.pid_alive(runtime.read_pid())
            receipt["slots"] = runtime.active_slots()
        else:
            getattr(runtime, args.command)()
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 1 if receipt.get("passed") is False else 0


def main() -> int:
    try:
        return run()
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        TimeoutError,
    ) as error:
        # Never echo arbitrary provider payloads, tokens or private filenames.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(error).__name__,
                    "message": "Local operator validation failed; check the configured targets and run the focused operator tests.",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
