"""Dateien für Nachrichten laden."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.discord_hub import files
from custom_components.discord_hub.files import async_load_attachments, normalize_spec


def test_text_forms_are_recognised():
    assert normalize_spec("https://x/y.jpg") == {"url": "https://x/y.jpg"}
    assert normalize_spec("camera.fuchs") == {"camera": "camera.fuchs"}
    assert normalize_spec("media-source://media_source/local/a.mp4") == {
        "media": "media-source://media_source/local/a.mp4"
    }
    assert normalize_spec("/media/a.mp4") == {"path": "/media/a.mp4"}


@pytest.mark.parametrize("spec", [{}, {"path": "a", "url": "b"}, 5, ["a"]])
def test_a_spec_needs_exactly_one_source(spec):
    with pytest.raises(ServiceValidationError) as err:
        normalize_spec(spec)
    assert err.value.translation_key == "file_source"


async def test_nothing_to_load(hass):
    assert await async_load_attachments(hass, None) == []
    assert await async_load_attachments(hass, []) == []


async def test_local_file(hass, tmp_path):
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    video = tmp_path / "aufnahme.mp4"
    video.write_bytes(b"video")
    [attachment] = await async_load_attachments(hass, [str(video)])
    assert (attachment.filename, attachment.data, attachment.content_type) == ("aufnahme.mp4", b"video", "video/mp4")


async def test_spoiler_and_filename(hass, tmp_path):
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    (tmp_path / "a.jpg").write_bytes(b"1")
    [attachment] = await async_load_attachments(
        hass, [{"path": str(tmp_path / "a.jpg"), "filename": "b.jpg", "spoiler": True}]
    )
    assert attachment.filename == "SPOILER_b.jpg"


async def test_path_outside_the_allowed_folders(hass, tmp_path):
    (tmp_path / "geheim.txt").write_text("x")
    with pytest.raises(ServiceValidationError) as err:
        await async_load_attachments(hass, [str(tmp_path / "geheim.txt")])
    assert err.value.translation_key == "path_not_allowed"


async def test_missing_file(hass, tmp_path):
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    with pytest.raises(ServiceValidationError) as err:
        await async_load_attachments(hass, [str(tmp_path / "gibt-es-nicht.mp4")])
    assert err.value.translation_key == "file_not_found"


async def test_file_over_the_cap(hass, tmp_path):
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    (tmp_path / "gross.bin").write_bytes(b"123456")
    with (
        patch.object(files, "MAX_FILE_BYTES", 5),
        pytest.raises(ServiceValidationError) as err,
    ):
        await async_load_attachments(hass, [str(tmp_path / "gross.bin")])
    assert err.value.translation_key == "file_too_big"


async def test_too_many_files(hass):
    with pytest.raises(ServiceValidationError) as err:
        await async_load_attachments(hass, ["camera.a"] * 11)
    assert err.value.translation_key == "too_many_files"


async def test_url_must_be_allowed(hass):
    with pytest.raises(ServiceValidationError) as err:
        await async_load_attachments(hass, ["https://beispiel.de/bild.jpg"])
    assert err.value.translation_key == "url_not_allowed"


async def test_url_download(hass, aioclient_mock):
    hass.config.allowlist_external_urls = {"https://beispiel.de"}
    aioclient_mock.get("https://beispiel.de/bild.jpg", content=b"jpg", headers={"Content-Type": "image/jpeg"})
    [attachment] = await async_load_attachments(hass, ["https://beispiel.de/bild.jpg"])
    assert (attachment.filename, attachment.data, attachment.content_type) == ("bild.jpg", b"jpg", "image/jpeg")


async def test_url_download_failure(hass, aioclient_mock):
    hass.config.allowlist_external_urls = {"https://beispiel.de"}
    aioclient_mock.get("https://beispiel.de/bild.jpg", status=404)
    with pytest.raises(HomeAssistantError) as err:
        await async_load_attachments(hass, ["https://beispiel.de/bild.jpg"])
    assert err.value.translation_key == "download_failed"


async def test_camera_snapshot(hass):
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)) as get_image:
        [attachment] = await async_load_attachments(hass, ["camera.fuchsrevier"])
    get_image.assert_awaited_once_with(hass, "camera.fuchsrevier")
    assert attachment.filename == "fuchsrevier.jpg"
    assert attachment.content_type == "image/jpeg"


async def test_local_media_source(hass, tmp_path):
    # kein allowlist_external_dirs nötig: die Medienquelle ist schon auf die Medienordner beschränkt
    assert not hass.config.is_allowed_path(str(tmp_path / "clip.mp4"))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip")
    play = SimpleNamespace(path=clip, url="/media/local/clip.mp4", mime_type="video/mp4")
    with patch.object(files.media_source, "async_resolve_media", AsyncMock(return_value=play)):
        [attachment] = await async_load_attachments(hass, ["media-source://media_source/local/clip.mp4"])
    assert (attachment.filename, attachment.data, attachment.content_type) == ("clip.mp4", b"clip", "video/mp4")


async def test_remote_media_source_is_refused(hass):
    play = SimpleNamespace(path=None, url="https://x/clip.mp4", mime_type="video/mp4")
    with (
        patch.object(files.media_source, "async_resolve_media", AsyncMock(return_value=play)),
        pytest.raises(ServiceValidationError) as err,
    ):
        await async_load_attachments(hass, ["media-source://cloud/clip"])
    assert err.value.translation_key == "media_not_local"
