"""Private local image storage for owned/consented images.

Bytes live on disk, one file per image ID, in a directory that must be outside the
repository or inside its git-ignored `data/` folder. The database stores only the object
key, hashes, consent basis and retention deadline (`telemetry.images`). Deletion removes the
file and keeps a tombstone row (`deleted_at`) so locked manifests never change silently.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, insert, select, update

from foodvision.data.models import images

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_IN_REPO = REPO_ROOT / "data"  # git-ignored (/data/ in .gitignore)


class UnsafeStorageRoot(ValueError):
    pass


@dataclass(frozen=True)
class StoredImage:
    image_id: uuid.UUID
    object_key: str
    original_sha256: str
    retention_until: datetime


def _check_root(root: Path) -> Path:
    root = root.resolve()
    if root.is_relative_to(REPO_ROOT) and not root.is_relative_to(ALLOWED_IN_REPO):
        raise UnsafeStorageRoot(
            f"{root} is inside the repository; use a path outside it or under {ALLOWED_IN_REPO}"
        )
    return root


class LocalObjectStore:
    def __init__(self, root: Path | str) -> None:
        self.root = _check_root(Path(root))

    def path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        if not path.is_relative_to(self.root):
            raise UnsafeStorageRoot("object key escapes the storage root")
        return path

    def write(self, object_key: str, data: bytes) -> None:
        path = self.path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(path)

    def read(self, object_key: str) -> bytes:
        return self.path(object_key).read_bytes()

    def exists(self, object_key: str) -> bool:
        return self.path(object_key).exists()

    def remove(self, object_key: str) -> None:
        self.path(object_key).unlink(missing_ok=True)


def store_image(
    conn: Connection,
    store: LocalObjectStore,
    data: bytes,
    *,
    consent_basis: str,
    retention_days: int,
    now: datetime,
    processed_sha256: str | None = None,
    size_px: tuple[int, int] | None = None,
    is_synthetic: bool = False,
) -> StoredImage:
    """Write bytes to the private store and register metadata (never bytes) in Postgres."""
    if not consent_basis.strip():
        raise ValueError("consent_basis is required for stored images")
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    image_id = uuid.uuid4()
    object_key = f"{image_id.hex[:2]}/{image_id.hex}"
    original_sha256 = hashlib.sha256(data).hexdigest()
    retention_until = now + timedelta(days=retention_days)
    store.write(object_key, data)
    conn.execute(
        insert(images).values(
            image_id=image_id,
            object_key=object_key,
            original_sha256=original_sha256,
            processed_sha256=processed_sha256,
            width_px=size_px[0] if size_px else None,
            height_px=size_px[1] if size_px else None,
            consent_basis=consent_basis,
            retention_until=retention_until,
            is_synthetic=is_synthetic,
        )
    )
    return StoredImage(image_id, object_key, original_sha256, retention_until)


def delete_image(
    conn: Connection, store: LocalObjectStore, image_id: uuid.UUID, now: datetime
) -> bool:
    """Remove the bytes and tombstone the row. Returns False if already deleted/unknown."""
    object_key = conn.execute(
        select(images.c.object_key).where(
            images.c.image_id == image_id, images.c.deleted_at.is_(None)
        )
    ).scalar_one_or_none()
    if object_key is None:
        return False
    store.remove(object_key)
    conn.execute(update(images).where(images.c.image_id == image_id).values(deleted_at=now))
    return True


def purge_expired(conn: Connection, store: LocalObjectStore, now: datetime) -> int:
    """Delete every image whose retention deadline has passed. Returns how many."""
    expired = (
        conn.execute(
            select(images.c.image_id).where(
                images.c.retention_until <= now, images.c.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    return sum(delete_image(conn, store, image_id, now) for image_id in expired)
