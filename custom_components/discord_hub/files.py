"""Dateien für Nachrichten laden: lokaler Pfad, Adresse, Kamerabild oder Medienquelle."""

from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.components import camera, media_source
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Attachment
from .const import DOMAIN, MAX_FILE_BYTES, MAX_FILES

SOURCE_KEYS = ("path", "url", "camera", "media")


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders or None
    )


def normalize_spec(spec: Any) -> dict[str, Any]:
    """Eine Angabe als Text (Pfad, Adresse, Kamera-Entity, Medienquelle) oder als Objekt in ein Objekt umwandeln."""
    if isinstance(spec, str):
        text = spec.strip()
        if text.startswith(("http://", "https://")):
            return {"url": text}
        if text.startswith("media-source://"):
            return {"media": text}
        if text.startswith("camera."):
            return {"camera": text}
        return {"path": text}
    if isinstance(spec, dict):
        given = [key for key in SOURCE_KEYS if spec.get(key)]
        if len(given) != 1:
            raise _error("file_source", spec=str(spec))
        return dict(spec)
    raise _error("file_source", spec=str(spec))


def _guess(filename: str, content_type: str | None = None) -> str:
    return (content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream").split(";")[0].strip()


def _read_file(path: str) -> bytes:
    size = Path(path).stat().st_size
    if size > MAX_FILE_BYTES:
        raise _error("file_too_big", name=Path(path).name, limit=str(MAX_FILE_BYTES // (1024 * 1024)))
    return Path(path).read_bytes()


async def _load_path(hass: HomeAssistant, path: str) -> tuple[str, bytes, str | None]:
    if not hass.config.is_allowed_path(path):
        raise _error("path_not_allowed", path=path)
    try:
        data = await hass.async_add_executor_job(_read_file, path)
    except FileNotFoundError as err:
        raise _error("file_not_found", path=path) from err
    except OSError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="file_unreadable", translation_placeholders={"path": path}
        ) from err
    return Path(path).name, data, None


async def _load_url(hass: HomeAssistant, url: str) -> tuple[str, bytes, str | None]:
    if not hass.config.is_allowed_external_url(url):
        raise _error("url_not_allowed", url=url)
    name = unquote(PurePosixPath(urlparse(url).path).name) or "datei"
    try:
        async with async_get_clientsession(hass).get(url) as resp:
            if resp.status != 200:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="download_failed",
                    translation_placeholders={"url": url, "details": f"HTTP {resp.status}"},
                )
            too_big = _error("file_too_big", name=name, limit=str(MAX_FILE_BYTES // (1024 * 1024)))
            if int(resp.headers.get("Content-Length") or 0) > MAX_FILE_BYTES:
                raise too_big
            data = bytearray()
            async for chunk in resp.content.iter_chunked(64 * 1024):
                data += chunk
                if len(data) > MAX_FILE_BYTES:
                    raise too_big
            return name, bytes(data), resp.headers.get("Content-Type")
    except (TimeoutError, aiohttp.ClientError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="download_failed",
            translation_placeholders={"url": url, "details": str(err)},
        ) from err


async def _load_camera(hass: HomeAssistant, entity_id: str) -> tuple[str, bytes, str | None]:
    image = await camera.async_get_image(hass, entity_id)
    extension = mimetypes.guess_extension(image.content_type) or ".jpg"
    if extension == ".jpe":
        extension = ".jpg"
    return f"{entity_id.split('.', 1)[1]}{extension}", image.content, image.content_type


async def _load_media(hass: HomeAssistant, uri: str) -> tuple[str, bytes, str | None]:
    play = await media_source.async_resolve_media(hass, uri, None)
    if play.path is None:
        raise _error("media_not_local", uri=uri)
    name, data, _ = await _load_path(hass, str(play.path))
    return name, data, play.mime_type


async def async_load_attachments(hass: HomeAssistant, specs: list[Any] | None) -> list[Attachment]:
    """Alle angegebenen Dateien laden. Höchstens so viele, wie Discord an eine Nachricht hängen lässt."""
    if not specs:
        return []
    if len(specs) > MAX_FILES:
        raise _error("too_many_files", limit=str(MAX_FILES))
    attachments: list[Attachment] = []
    for raw in specs:
        spec = normalize_spec(raw)
        if spec.get("path"):
            name, data, content_type = await _load_path(hass, str(spec["path"]))
        elif spec.get("url"):
            name, data, content_type = await _load_url(hass, str(spec["url"]))
        elif spec.get("camera"):
            name, data, content_type = await _load_camera(hass, str(spec["camera"]))
        else:
            name, data, content_type = await _load_media(hass, str(spec["media"]))
        filename = str(spec.get("filename") or name)
        if spec.get("spoiler") and not filename.startswith("SPOILER_"):
            filename = f"SPOILER_{filename}"
        attachments.append(Attachment(filename, data, _guess(filename, content_type)))
    return attachments
