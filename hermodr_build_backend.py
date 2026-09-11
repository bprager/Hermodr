"""Small reproducible PEP 517 wheel backend for the dependency-free service."""

import base64
import hashlib
import os
from pathlib import Path
import zipfile


VERSION = "0.1.0.dev0"
DIST_INFO = f"hermodr-{VERSION}.dist-info"


def get_requires_for_build_wheel(config_settings=None):
    del config_settings
    return []


def _files(root: Path):
    for source_root, target_root in ((root / "src" / "hermodr", "hermodr"), (root / "contracts", "hermodr/contracts")):
        for path in sorted(source_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                yield path, f"{target_root}/{path.relative_to(source_root).as_posix()}"


def _digest(content: bytes) -> str:
    value = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={value}"


def _write(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content, compresslevel=9)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    del config_settings, metadata_directory
    root = Path(__file__).resolve().parent
    output = Path(wheel_directory)
    output.mkdir(parents=True, exist_ok=True)
    wheel_name = f"hermodr-{VERSION}-py3-none-any.whl"
    records = []
    metadata = (
        "Metadata-Version: 2.4\nName: hermodr\nVersion: " + VERSION
        + "\nSummary: Local-first deterministic location ingestion service\nRequires-Python: >=3.13\n\n"
    ).encode()
    wheel = b"Wheel-Version: 1.0\nGenerator: hermodr-build-backend\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    entry_points = b"[console_scripts]\nhermodr=hermodr.cli:main\n"
    entries = list(_files(root))
    commit = os.environ.get("HERMODR_BUILD_COMMIT", "unknown")
    if not commit.replace("-", "").replace("_", "").isalnum() or len(commit) > 64:
        commit = "unknown"
    artifact = f'VERSION = "{VERSION}"\nCOMMIT = "{commit}"\n'.encode()
    with zipfile.ZipFile(output / wheel_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in entries:
            content = path.read_bytes()
            _write(archive, name, content)
            records.append((name, _digest(content), str(len(content))))
        _write(archive, "hermodr/_artifact.py", artifact)
        records.append(("hermodr/_artifact.py", _digest(artifact), str(len(artifact))))
        for name, content in (
            (f"{DIST_INFO}/METADATA", metadata),
            (f"{DIST_INFO}/WHEEL", wheel),
            (f"{DIST_INFO}/entry_points.txt", entry_points),
        ):
            _write(archive, name, content)
            records.append((name, _digest(content), str(len(content))))
        record_name = f"{DIST_INFO}/RECORD"
        record = "".join(f"{name},{digest},{size}\n" for name, digest, size in records) + f"{record_name},,\n"
        _write(archive, record_name, record.encode())
    return wheel_name
