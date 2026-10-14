"""Private atomic cache, content-addressed attachment bytes, no arbitrary output paths."""

import json
import os
import tempfile
from pathlib import Path


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("symlink_not_allowed")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Cache:
    def __init__(self, root):
        self.root = Path(root)

    def read(self, key):
        path = self.root / (key + ".json")
        return json.loads(path.read_text()) if path.exists() else None

    def write(self, key, value):
        private_write(
            self.root / (key + ".json"),
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode(),
        )
