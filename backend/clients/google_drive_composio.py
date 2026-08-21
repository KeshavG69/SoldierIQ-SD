"""
Google Drive client backed by Composio (drop-in replacement for the manual
OAuth GoogleDriveClient).

We no longer manage Google OAuth tokens ourselves — Composio owns the OAuth
flow + refresh. Each of OUR users is identified to Composio by their real
user_id (the Composio "entity"); one connection per user. Connect uses
Composio's hosted-link flow (`connected_accounts.link`), exactly like the
SharePoint integration.

This class keeps the SAME public surface the ingestion tasks already consume:
  - GoogleDriveComposioClient.for_user(org, user) -> client | None
  - client.list_files() / client.list_files_in_folders([ids]) -> async iter DriveFile
  - client.download_file(file_id, mime_type) -> (bytes, effective_mime)
so the tasks need only swap which client they import.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from app.logger import logger
from app.settings import settings


class GoogleDriveError(RuntimeError):
    """Anything from Drive/Composio that isn't a success."""


@dataclass
class DriveFile:
    """One discovered file's metadata (same shape as the manual client)."""
    id: str
    name: str
    mime_type: str
    size: int
    modified_at: Optional[datetime]
    web_url: Optional[str]


# Google-native (Workspace) export targets — matches the pipeline's extractor
# routing (text/csv are decoded cleanly; PDF is worse for text extraction).
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_FOLDER_MIME = "application/vnd.google-apps.folder"

_client_singleton = None
_client_lock = threading.Lock()


def _composio():
    global _client_singleton
    if _client_singleton is None:
        with _client_lock:
            if _client_singleton is None:
                from composio import Composio
                if not settings.COMPOSIO_API_KEY:
                    raise GoogleDriveError("COMPOSIO_API_KEY is not configured")
                _client_singleton = Composio(api_key=settings.COMPOSIO_API_KEY)
                logger.info("✅ Composio client initialized (Google Drive)")
    return _client_singleton


class GoogleDriveComposioClient:
    TOOLKIT = "googledrive"

    def __init__(self, user_id: str):
        if not user_id:
            raise GoogleDriveError("user_id is required")
        self.user_id = str(user_id)
        self._c = _composio()

    # ---- connection management (no tokens stored on our side) -----------
    @classmethod
    async def for_user(cls, organization_id: str, user_id: str) -> Optional["GoogleDriveComposioClient"]:
        """Return a client if this user has an ACTIVE Composio Drive
        connection, else None (org_id kept for signature compatibility)."""
        client = cls(user_id)
        status = await asyncio.to_thread(client.connection_status)
        return client if status.get("connected") else None

    def initiate_connection(self, callback_url: Optional[str] = None) -> Dict[str, Optional[str]]:
        req = self._c.connected_accounts.link(
            user_id=self.user_id,
            auth_config_id=settings.COMPOSIO_GDRIVE_AUTH_CONFIG_ID,
            callback_url=callback_url,
        )
        return {
            "auth_url": getattr(req, "redirect_url", None),
            "connection_id": getattr(req, "id", None),
        }

    def _list_my_connections(self) -> List[Any]:
        try:
            res = self._c.connected_accounts.list(
                user_ids=[self.user_id], toolkit_slugs=[self.TOOLKIT]
            )
        except TypeError:
            res = self._c.connected_accounts.list()
        items = getattr(res, "items", res) or []
        mine: List[Any] = []
        for a in items:
            tk = getattr(a, "toolkit", None)
            slug = getattr(tk, "slug", tk)
            auid = getattr(a, "user_id", None)
            if slug == self.TOOLKIT and auid in (None, self.user_id):
                mine.append(a)
        return mine

    def connection_status(self) -> Dict[str, Any]:
        mine = self._list_my_connections()
        active = next(
            (a for a in mine if str(getattr(a, "status", "")).upper() == "ACTIVE"), None
        )
        if active is not None:
            return {"connected": True, "status": "ACTIVE", "connection_id": getattr(active, "id", None)}
        if mine:
            a = mine[0]
            return {"connected": False, "status": str(getattr(a, "status", "")).upper() or None,
                    "connection_id": getattr(a, "id", None)}
        return {"connected": False, "status": None, "connection_id": None}

    def disconnect(self) -> int:
        n = 0
        for a in self._list_my_connections():
            try:
                self._c.connected_accounts.delete(getattr(a, "id"))
                n += 1
            except Exception as e:  # pragma: no cover
                logger.warning(f"Drive disconnect failed for {getattr(a, 'id', '?')}: {e}")
        return n

    # ---- tool execution helper ------------------------------------------
    def _execute(self, slug: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._c.tools.execute(
            slug, arguments, user_id=self.user_id, dangerously_skip_version_check=True
        )
        if isinstance(resp, dict):
            ok = resp.get("successful", True); err = resp.get("error"); data = resp.get("data")
        else:
            ok = getattr(resp, "successful", True); err = getattr(resp, "error", None); data = getattr(resp, "data", None)
        if not ok:
            raise GoogleDriveError(f"{slug} failed: {err}")
        return data or {}

    @staticmethod
    def _files_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            for k in ("files", "value", "items", "results"):
                if isinstance(data.get(k), list):
                    return data[k]
            inner = data.get("data")
            if isinstance(inner, dict):
                return GoogleDriveComposioClient._files_list(inner)
        return []

    @staticmethod
    def _to_drivefile(f: Dict[str, Any]) -> DriveFile:
        modified = None
        raw = f.get("modifiedTime") or f.get("modifiedDate")
        if raw:
            try:
                modified = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                modified = None
        return DriveFile(
            id=f.get("id"),
            name=f.get("name") or f.get("title") or "Untitled",
            mime_type=f.get("mimeType") or "application/octet-stream",
            size=int(f.get("size") or f.get("fileSize") or 0),
            modified_at=modified,
            web_url=f.get("webViewLink") or f.get("alternateLink"),
        )

    # ---- listing --------------------------------------------------------
    def _list_children_sync(self, folder_id: Optional[str]) -> List[Dict[str, Any]]:
        """One folder's direct children (paginated). folder_id=None → root."""
        out: List[Dict[str, Any]] = []
        page_token = None
        q = f"'{folder_id}' in parents and trashed = false" if folder_id else "'root' in parents and trashed = false"
        while True:
            args: Dict[str, Any] = {
                "q": q,
                "pageSize": 200,
                "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                args["pageToken"] = page_token
            data = self._execute("GOOGLEDRIVE_FIND_FILE", args)
            out.extend(self._files_list(data))
            page_token = data.get("nextPageToken") if isinstance(data, dict) else None
            if not page_token:
                break
        return out

    async def _walk(self, folder_ids: Optional[List[str]]) -> AsyncIterator[DriveFile]:
        """BFS over folder tree(s); yields FILE DriveFiles (folders traversed).
        folder_ids=None → whole drive from root."""
        queue: List[Optional[str]] = list(folder_ids) if folder_ids else [None]
        seen: set = set()
        while queue:
            fid = queue.pop(0)
            key = fid or "root"
            if key in seen:
                continue
            seen.add(key)
            try:
                children = await asyncio.to_thread(self._list_children_sync, fid)
            except GoogleDriveError as e:
                logger.warning(f"[gdrive] list children failed (folder={key}): {e}")
                continue
            for ch in children:
                if ch.get("mimeType") == _FOLDER_MIME:
                    if ch.get("id"):
                        queue.append(ch["id"])
                else:
                    yield self._to_drivefile(ch)

    async def list_files(self) -> AsyncIterator[DriveFile]:
        async for f in self._walk(None):
            yield f

    async def list_files_in_folders(self, folder_ids: List[str]) -> AsyncIterator[DriveFile]:
        async for f in self._walk(folder_ids):
            yield f

    # ---- download -------------------------------------------------------
    def _download_sync(self, file_id: str, mime_type: str) -> Tuple[bytes, str]:
        args: Dict[str, Any] = {"fileId": file_id}
        # For Google-native docs, ask Composio to export to our preferred text
        # format (instead of its default PDF), so extraction stays clean.
        if mime_type in _EXPORT_MIME:
            args["mime_type"] = _EXPORT_MIME[mime_type]

        data = self._execute("GOOGLEDRIVE_DOWNLOAD_FILE", args)
        content = data.get("downloaded_file_content") or data.get("content") or {}
        # Composio sometimes returns this as a python-repr string; normalize.
        if isinstance(content, str):
            import ast
            try:
                content = ast.literal_eval(content)
            except (ValueError, SyntaxError):
                content = {}
        s3url = content.get("s3url") or content.get("s3Url")
        eff_mime = content.get("mimetype") or content.get("mimeType") or _EXPORT_MIME.get(mime_type, mime_type)
        if not s3url:
            raise GoogleDriveError(f"no download locator returned for {file_id}")

        r = httpx.get(s3url, timeout=180, follow_redirects=True)
        r.raise_for_status()
        return r.content, eff_mime

    async def download_file(self, file_id: str, mime_type: str) -> Tuple[bytes, str]:
        return await asyncio.to_thread(self._download_sync, file_id, mime_type)

    # ---- picker backends (in-app file/folder pickers) -------------------
    def _list_files_page_sync(self, page_token: Optional[str], page_size: int, search: Optional[str]) -> Dict[str, Any]:
        q = ["trashed = false", "mimeType != '%s'" % _FOLDER_MIME]
        if search:
            safe = search.replace("'", "\\'")
            q.append(f"name contains '{safe}'")
        args: Dict[str, Any] = {
            "q": " and ".join(q),
            "pageSize": min(max(page_size, 1), 100),
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if page_token:
            args["pageToken"] = page_token
        data = self._execute("GOOGLEDRIVE_FIND_FILE", args)
        files = [
            {
                "id": f.get("id"),
                "name": f.get("name", "(unnamed)"),
                "mime_type": f.get("mimeType", ""),
                "size": int(f.get("size") or 0),
                "modified_time": f.get("modifiedTime"),
                "web_view_link": f.get("webViewLink"),
            }
            for f in self._files_list(data)
        ]
        return {"files": files, "next_page_token": data.get("nextPageToken") if isinstance(data, dict) else None}

    async def list_files_page(self, page_token: Optional[str] = None, page_size: int = 50, search: Optional[str] = None) -> Dict[str, Any]:
        return await asyncio.to_thread(self._list_files_page_sync, page_token, page_size, search)

    def _list_folders_sync(self) -> List[Dict[str, Any]]:
        raw: List[Dict[str, Any]] = []
        page_token = None
        while True:
            args: Dict[str, Any] = {
                "q": f"mimeType = '{_FOLDER_MIME}' and trashed = false",
                "pageSize": 200,
                "fields": "nextPageToken, files(id, name, parents)",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                args["pageToken"] = page_token
            data = self._execute("GOOGLEDRIVE_FIND_FILE", args)
            raw.extend(self._files_list(data))
            page_token = data.get("nextPageToken") if isinstance(data, dict) else None
            if not page_token:
                break

        by_id = {f["id"]: f for f in raw if f.get("id")}

        def path_of(f: Dict[str, Any]) -> str:
            parts = [f.get("name", "")]
            seen = set()
            cur = f
            while cur.get("parents"):
                pid = cur["parents"][0]
                if pid in seen or pid not in by_id:
                    break
                seen.add(pid)
                cur = by_id[pid]
                parts.append(cur.get("name", ""))
            return "/".join(reversed([p for p in parts if p]))

        return [
            {"id": f["id"], "name": f.get("name"), "parents": f.get("parents"),
             "path": path_of(f), "shared_drive": None}
            for f in raw if f.get("id")
        ]

    async def list_folders(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_folders_sync)


def get_google_drive_client(user_id: str) -> GoogleDriveComposioClient:
    return GoogleDriveComposioClient(user_id)
