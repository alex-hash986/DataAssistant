"""Archive project storage. Stop the application first for a consistent snapshot."""

import argparse
import tarfile
from datetime import datetime
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIRS = ("chats", "uploads", "outputs")


def archive_members(snapshot: tarfile.TarFile, path: Path) -> None:
    if path.name.casefold().endswith(".env"):
        return
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT / "storage"):
        raise ValueError(f"Unexpected storage path: {path.relative_to(ROOT)}")
    if not (path.is_file() or path.is_dir()):
        raise ValueError(f"Unsupported storage entry: {path.relative_to(ROOT)}")

    member = snapshot.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
    if path.is_dir():
        snapshot.addfile(member)
        for child in sorted(path.iterdir()):
            archive_members(snapshot, child)
    else:
        with path.open("rb") as source:
            snapshot.addfile(member, source)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify_restore(archive: Path, target: Path) -> None:
    with tarfile.open(archive, "r:gz") as snapshot:
        members = snapshot.getmembers()
        snapshot.extractall(target, filter="data")

    manifest = {member.name for member in members if member.isfile()}
    restored_files = {path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()}
    if restored_files != manifest:
        raise ValueError("Restored file list differs from the archive manifest")
    if not all((target / "storage" / name).is_dir() for name in STORAGE_DIRS):
        raise ValueError("A storage directory is missing after restore")
    for name in manifest:
        if sha256(ROOT / name) != sha256(target / name):
            raise ValueError(f"Restored file differs from source: {name}")
    print(f"Restore verified: {len(manifest)} files (SHA-256), all 3 storage directories")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-restore", action="store_true", help="Test extraction in a temporary project folder")
    args = parser.parse_args()
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"data-assistant-{timestamp}.tar.gz"

    with TemporaryDirectory(prefix=".backup-", dir=backup_dir) as temp:
        temporary = Path(temp)
        archive = temporary / destination.name
        with tarfile.open(archive, "w:gz", dereference=True) as snapshot:
            for name in STORAGE_DIRS:
                directory = ROOT / "storage" / name
                if not directory.is_dir():
                    raise FileNotFoundError(directory)
                archive_members(snapshot, directory)
        if args.verify_restore:
            verify_restore(archive, temporary / "restore")
        archive.replace(destination)
    print(f"Archive: {destination.relative_to(ROOT)}")
    print(f"Archive SHA-256: {sha256(destination)}")


if __name__ == "__main__":
    main()
