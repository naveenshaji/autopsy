"""Durable, immutable JSON recovery snapshots and opt-in iCloud Drive copies.

The local snapshot is authoritative.  A verified copy in the iCloud Drive folder
does not prove that Apple's sync service has uploaded it to its servers.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _storage_lock(app_support: Path) -> Iterator[None]:
    directory = app_support / "Config"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "backup-storage.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_write_bytes(path: Path, data: bytes, *, replace: bool = False) -> None:
    """Publish complete bytes durably; callers serialize immutable publications.

    Tempfiles share the target filesystem. Mutable settings use atomic replace;
    immutable snapshots use atomic exclusive link publication so even another
    installation cannot race the collision check and overwrite existing bytes.
    Locking stays local, so a cloud folder never contains a live lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace and (path.exists() or path.is_symlink()):
        raise FileExistsError(f"refusing to overwrite existing backup: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".autopsy-backup-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def backup_manifest_path(path: str | Path) -> Path:
    path = Path(path).expanduser()
    return path.with_name(path.name + ".sha256")


def unique_backup_path(*, app_support: str | Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # A caller-provided timestamp remains a filename component, never a path.
    stamp = "".join(character for character in stamp if character.isalnum() or character in "-_") or "snapshot"
    return Path(app_support).expanduser() / "Backups" / f"autopsy-memory-{stamp}-{uuid.uuid4().hex}.json"


def verify_backup_snapshot(path: str | Path, *, require_manifest: bool = False) -> dict[str, Any]:
    """Verify bytes and JSON without changing the backup or parsing graph state.

    Historical JSON exports without a sidecar remain readable.  A present but
    invalid sidecar always fails closed, including for historical snapshots.
    """
    return _verify_backup_snapshot(path, require_manifest=require_manifest, validate_json=True)


def _verify_backup_snapshot(
    path: str | Path, *, require_manifest: bool = False, validate_json: bool
) -> dict[str, Any]:
    path = Path(path).expanduser()
    manifest_path = backup_manifest_path(path)
    report: dict[str, Any] = {"valid": False, "path": str(path), "manifest": str(manifest_path)}
    try:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        report.update({"bytes": len(data), "sha256": digest})
        if manifest_path.exists() or manifest_path.is_symlink():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                raise ValueError("unsupported backup integrity manifest")
            if manifest.get("algorithm") != "sha256" or manifest.get("sha256") != digest:
                raise ValueError("backup SHA-256 checksum does not match its manifest")
            if manifest.get("bytes") != len(data):
                raise ValueError("backup byte count does not match its manifest")
            if manifest.get("filename") != path.name:
                raise ValueError("backup filename does not match its manifest")
            report["integrity"] = "verified"
        elif require_manifest:
            raise ValueError("backup integrity manifest is missing")
        else:
            report["integrity"] = "legacy_unverified"
        if validate_json:
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("backup JSON must be an object")
            marker = payload.get("backup_integrity")
            if marker is not None:
                if marker != {"schema_version": 1, "algorithm": "sha256", "manifest_required": True}:
                    raise ValueError("unsupported backup integrity marker")
                if report.get("integrity") != "verified":
                    raise ValueError("backup integrity manifest is missing for this protected snapshot")
        report["valid"] = True
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        report["error"] = str(exc)
    return report


def write_backup_snapshot(
    payload: dict[str, Any], *, app_support: str | Path, output: str | Path | None = None
) -> dict[str, Any]:
    """Write a compact restore-compatible snapshot, then verify its sidecar.

    Local failures raise so callers cannot report a successful recovery copy.
    An existing explicit output path is never overwritten, even if identical.
    """
    app_support = Path(app_support).expanduser()
    path = Path(output).expanduser() if output is not None else unique_backup_path(app_support=app_support)
    protected_payload = dict(payload)
    protected_payload["backup_integrity"] = {"schema_version": 1, "algorithm": "sha256", "manifest_required": True}
    data = _json_bytes(protected_payload)
    manifest = {
        "schema_version": 1,
        "algorithm": "sha256",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "filename": path.name,
        "created_at": _now(),
    }
    manifest_path = backup_manifest_path(path)
    with _storage_lock(app_support):
        if path.exists() or path.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
            raise FileExistsError(f"refusing to overwrite existing backup or manifest: {path}")
        # Publish the sidecar first. A failed integrity write must never expose
        # a new snapshot to latest-backup discovery as a legacy JSON export.
        _atomic_write_bytes(manifest_path, _json_bytes(manifest))
        _atomic_write_bytes(path, data)
    # Serialization already checked JSON. Recheck persisted bytes without
    # building a second full in-memory graph for a large snapshot.
    verification = _verify_backup_snapshot(path, require_manifest=True, validate_json=False)
    if not verification["valid"]:
        raise OSError(f"backup verification failed: {verification.get('error')}")
    return {
        "status": "created", "written": str(path), "bytes": len(data),
        "sha256": manifest["sha256"], "manifest": str(manifest_path),
        "verified": True, "created_at": manifest["created_at"],
    }


def default_icloud_directory() -> Path:
    return Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Autopsy" / "Backups"


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return payload


def _read_settings(app_support: Path) -> dict[str, Any]:
    path = app_support / "Config" / "backup-settings.json"
    if not path.exists():
        return {"schema_version": 1, "enabled": False, "directory": str(default_icloud_directory())}
    settings = _read_json_object(path)
    if settings.get("schema_version") != 1 or not isinstance(settings.get("enabled"), bool):
        raise ValueError("invalid backup settings schema or enabled flag")
    directory = settings.get("directory")
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError("invalid iCloud backup directory in settings")
    return settings


def _directory_availability(directory: Path) -> dict[str, Any]:
    """Never synthesize an absent iCloud container and mistake it for a drive."""
    directory = directory.expanduser()
    cloud_root = default_icloud_directory().parent.parent
    # This also protects explicitly configured subfolders of the default root.
    if directory == cloud_root or cloud_root in directory.parents:
        available = cloud_root.is_dir()
        return {"available": available, "kind": "icloud_drive", "root": str(cloud_root),
                "error": None if available else f"iCloud Drive is unavailable: {cloud_root}"}
    # Require a custom target to exist. Recreating its parent would otherwise
    # mistake a disconnected mount for an ordinary local directory.
    available = directory.is_dir()
    return {"available": available, "kind": "custom_directory", "root": str(directory),
            "error": None if available else f"configured backup directory is unavailable: {directory}"}


def icloud_backup_status(*, app_support: str | Path) -> dict[str, Any]:
    """Read only small local settings/receipts; do not hydrate cloud snapshots."""
    app_support = Path(app_support).expanduser()
    result: dict[str, Any] = {
        "settings_path": str(app_support / "Config" / "backup-settings.json"),
        "cloud_upload": "unknown", "remote_verified": False,
    }
    try:
        settings = _read_settings(app_support)
        result.update(settings)
        result["directory_status"] = _directory_availability(Path(settings["directory"]))
        result["status"] = "enabled" if settings["enabled"] else "disabled"
    except (OSError, ValueError, TypeError) as exc:
        result.update({"enabled": False, "status": "error", "error": str(exc)})
    receipt_path = app_support / "Config" / "backup-status.json"
    if receipt_path.exists():
        try:
            receipt = _read_json_object(receipt_path)
            result["last_attempt"] = receipt.get("last_attempt")
            result["latest_success"] = receipt.get("latest_success")
        except (OSError, ValueError, TypeError) as exc:
            result["receipt_error"] = str(exc)
    return result


def configure_icloud_backup(
    *, app_support: str | Path, enabled: bool, directory: str | Path | None = None
) -> dict[str, Any]:
    """Persist opt-in settings without touching the graph or uploading files."""
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    app_support = Path(app_support).expanduser()
    with _storage_lock(app_support):
        settings = _read_settings(app_support)
        settings["enabled"] = enabled
        if directory is not None:
            if not str(directory).strip():
                raise ValueError("iCloud backup directory must not be empty")
            settings["directory"] = str(Path(directory).expanduser().absolute())
        _atomic_write_bytes(app_support / "Config" / "backup-settings.json", _json_bytes(settings), replace=True)
    return icloud_backup_status(app_support=app_support)


def _persist_mirror_receipt(app_support: Path, receipt: dict[str, Any]) -> None:
    path = app_support / "Config" / "backup-status.json"
    with _storage_lock(app_support):
        previous = _read_json_object(path) if path.exists() else {}
        latest_success = previous.get("latest_success")
        if receipt.get("status") in {"copied", "already_present"}:
            latest_success = dict(receipt)
        _atomic_write_bytes(path, _json_bytes({"schema_version": 1, "last_attempt": receipt,
                                             "latest_success": latest_success}), replace=True)


def mirror_backup_to_icloud(path: str | Path, *, app_support: str | Path) -> dict[str, Any]:
    """Copy verified immutable bytes; report failures without undoing local work.

    Cloud failures are persisted separately from the user's settings and retain
    the previous successful receipt.  Retrying the same snapshot is idempotent.
    No snapshot is ever pruned or replaced.
    """
    app_support = Path(app_support).expanduser()
    source = Path(path).expanduser()
    receipt: dict[str, Any] = {
        "status": "error", "source": str(source), "attempted_at": _now(),
        "cloud_upload": "unknown", "remote_verified": False, "local_copy_verified": False,
    }
    try:
        settings = _read_settings(app_support)
        receipt["enabled"] = settings["enabled"]
        if not settings["enabled"]:
            receipt["status"] = "disabled"
            return receipt
        directory = Path(settings["directory"]).expanduser()
        availability = _directory_availability(directory)
        if not availability["available"]:
            raise OSError(availability["error"])
        verification = verify_backup_snapshot(source, require_manifest=True)
        if not verification["valid"]:
            raise ValueError(f"local backup verification failed: {verification.get('error')}")
        destination = directory / source.name
        receipt.update({"destination": str(destination), "sha256": verification["sha256"], "bytes": verification["bytes"]})
        with _storage_lock(app_support):
            # Read once and recheck the bytes actually copied, avoiding a race
            # between source verification and publication.
            data = source.read_bytes()
            manifest_data = backup_manifest_path(source).read_bytes()
            if hashlib.sha256(data).hexdigest() != verification["sha256"]:
                raise ValueError("local backup changed while preparing its iCloud copy")
            if destination.exists() or destination.is_symlink():
                existing = _verify_backup_snapshot(destination, validate_json=False)
                # A previous attempt may have published all snapshot bytes and
                # failed before its sidecar. Repair only an exact byte match.
                if existing["valid"] and existing.get("sha256") == verification["sha256"] and existing.get("integrity") == "legacy_unverified":
                    _atomic_write_bytes(backup_manifest_path(destination), manifest_data)
                    existing = _verify_backup_snapshot(destination, require_manifest=True, validate_json=False)
                if not existing["valid"] or existing.get("sha256") != verification["sha256"]:
                    raise FileExistsError(f"existing iCloud snapshot differs or is corrupt; preserved: {destination}")
                receipt["status"] = "already_present"
            else:
                destination_manifest = backup_manifest_path(destination)
                if destination_manifest.exists() or destination_manifest.is_symlink():
                    raise FileExistsError(f"existing iCloud manifest has no snapshot; preserved: {destination_manifest}")
                _atomic_write_bytes(destination, data)
                _atomic_write_bytes(destination_manifest, manifest_data)
                copied = _verify_backup_snapshot(destination, require_manifest=True, validate_json=False)
                if not copied["valid"] or copied.get("sha256") != verification["sha256"]:
                    raise OSError(f"iCloud copy verification failed: {copied.get('error')}")
                receipt["status"] = "copied"
            receipt["local_copy_verified"] = True
    except Exception as exc:
        receipt.update({"status": "error", "error": str(exc)})
    try:
        _persist_mirror_receipt(app_support, receipt)
    except Exception as exc:
        # A read-only/broken settings volume must not hide a successfully written
        # recovery copy or cause a successful memory mutation to fail.
        receipt["receipt_error"] = str(exc)
    return receipt
