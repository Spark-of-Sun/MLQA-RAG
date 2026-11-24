"""Object storage for original files.

Keys follow blueprint 10.1, `org_{id}/ws_{id}/doc_{id}/v{n}/original{ext}`, and are built server-side from
database UUIDs only, never from client input. MVP: local filesystem under `data/objects` (application-level
encryption and S3 are later stages, see docs/mvp.md).
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

EXTENSIONS = {"pdf": ".pdf", "docx": ".docx", "html": ".html", "xml": ".xml", "txt": ".txt"}


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @staticmethod
    def key(
        org_id: object, workspace_id: object, document_id: object, file_type: str, version: int = 1
    ) -> str:
        org, ws, doc = (str(UUID(str(v))) for v in (org_id, workspace_id, document_id))
        return f"org_{org}/ws_{ws}/doc_{doc}/v{version}/original{EXTENSIONS[file_type]}"

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("object key escapes the store")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        for parent in path.parents:
            if parent == self._root:
                break
            try:
                parent.rmdir()
            except OSError:
                break
