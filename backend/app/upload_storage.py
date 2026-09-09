"""Private Supabase objects; local paths are only an ephemeral image cache."""
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException


class UploadStorage:
    def __init__(self, url, key, bucket):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("SUPABASE_URL must be an HTTPS project URL")
        if not key or not re.fullmatch(r"[a-zA-Z0-9_-]+", bucket):
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY and SUPABASE_STORAGE_BUCKET are required")
        self.url = url.rstrip("/") + "/storage/v1/object/" + quote(bucket, safe="")
        self.headers = {"Authorization": "Bearer " + key, "apikey": key}

    @classmethod
    def from_env(cls, store):
        if store.backend != "postgres":
            return None
        return cls(os.environ.get("SUPABASE_URL", ""),
                   os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                   os.environ.get("SUPABASE_STORAGE_BUCKET", ""))

    def object_url(self, path):
        name = Path(path).name
        if not re.fullmatch(r"[a-f0-9]{64}\.(source|normalized)\.(jpg|png)", name):
            raise HTTPException(422, "Invalid image storage reference")
        return self.url + "/images/" + name

    def persist(self, metadata):
        for field in ("stored_path", "preserved_path"):
            path = Path(metadata[field])
            try:
                response = httpx.post(self.object_url(path), content=path.read_bytes(),
                    headers={**self.headers, "x-upsert": "true",
                             "Content-Type": "image/png" if path.suffix == ".png" else "image/jpeg"},
                    timeout=30, follow_redirects=False)
                if response.status_code not in (200, 201):
                    raise HTTPException(503, "Image storage unavailable")
            except (httpx.RequestError, OSError):
                raise HTTPException(503, "Image storage unavailable") from None

    def restore(self, path):
        url = self.object_url(path)
        if path.is_file():
            return
        try:
            response = httpx.get(url, headers=self.headers, timeout=30, follow_redirects=False)
            if response.status_code != 200:
                raise HTTPException(503, "Image storage unavailable")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + "." + uuid4().hex)
            temporary.write_bytes(response.content)
            temporary.replace(path)
        except (httpx.RequestError, OSError):
            raise HTTPException(503, "Image storage unavailable") from None
