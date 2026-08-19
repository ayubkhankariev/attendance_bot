"""Получение снимка с камеры видеонаблюдения.

Поддерживается:
  * HTTP-снимок Hikvision ISAPI (камера или регистратор NVR):
      http://IP/ISAPI/Streaming/channels/101/picture
      http://NVR_IP/ISAPI/Streaming/channels/401/picture   (канал 4 на NVR)
  * RTSP-поток (если ISAPI выключен): rtsp://user:pass@IP:554/Streaming/Channels/101
  * Локальная USB-камера (для тестов): type: webcam, index: 0
  * Статичный файл-снимок (для тестов): type: file, path: путь/к/фото.jpg
"""
from __future__ import annotations

import logging
import pathlib

import requests
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


def grab_snapshot(cam: dict) -> bytes:
    """Возвращает JPEG-байты снимка с камеры по её конфигурации."""
    cam_type = str(cam.get("type") or "").strip().lower()
    if cam_type == "webcam":
        return _grab_webcam(cam.get("index", 0))
    if cam_type == "file":
        return _grab_file(cam.get("path"))
    url = str(cam.get("url") or "").strip()
    if not url:
        raise CameraError("В конфигурации камеры не указан url")
    if url.lower().startswith("rtsp://"):
        return _grab_rtsp(url)
    return _grab_http(url, cam.get("username"), cam.get("password"))


def _grab_webcam(index) -> bytes:
    try:
        import cv2
    except ImportError as e:
        raise CameraError("Для webcam нужен opencv-python (pip install opencv-python)") from e
    cap = cv2.VideoCapture(int(index), cv2.CAP_DSHOW)
    try:
        if not cap.isOpened():
            raise CameraError(
                f"Не удалось открыть веб-камеру (индекс {index}) — возможно, "
                "она занята другой программой (iVMS-4200, Zoom, Teams...)"
            )
        # первые кадры часто недоэкспонированы, пока камера настраивает автоэкспозицию
        frame = None
        for _ in range(5):
            ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise CameraError(f"Не удалось прочитать кадр с веб-камеры (индекс {index})")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise CameraError("Не удалось закодировать кадр в JPEG")
    return buf.tobytes()


def _grab_file(path) -> bytes:
    if not path:
        raise CameraError("В конфигурации камеры не указан path")
    p = pathlib.Path(path)
    if not p.exists():
        raise CameraError(f"Файл снимка не найден: {path}")
    return p.read_bytes()


def _grab_http(url: str, username, password) -> bytes:
    last_err = None
    # Hikvision обычно использует Digest-аутентификацию, но пробуем и Basic
    auth_variants = [None]
    if username:
        auth_variants = [
            HTTPDigestAuth(username, password or ""),
            HTTPBasicAuth(username, password or ""),
        ]
    for auth in auth_variants:
        try:
            r = requests.get(url, auth=auth, timeout=20)
            if r.status_code == 401:
                last_err = CameraError("Неверный логин/пароль камеры (401)")
                continue
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            if "image" not in ctype and not r.content[:3] == b"\xff\xd8\xff":
                raise CameraError(
                    f"Камера вернула не изображение (Content-Type={ctype!r}). "
                    "Проверьте URL снимка."
                )
            if len(r.content) < 1000:
                raise CameraError("Камера вернула слишком маленький файл — проверьте URL")
            return r.content
        except CameraError as e:
            last_err = e
        except Exception as e:
            last_err = CameraError(f"Ошибка запроса к камере: {e}")
    raise last_err or CameraError("Не удалось получить снимок")


def _grab_rtsp(url: str) -> bytes:
    try:
        import cv2
    except ImportError as e:
        raise CameraError("Для RTSP нужен opencv-python (pip install opencv-python)") from e
    cap = cv2.VideoCapture(url)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise CameraError(f"Не удалось прочитать кадр из RTSP-потока: {url}")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise CameraError("Не удалось закодировать кадр в JPEG")
    return buf.tobytes()
