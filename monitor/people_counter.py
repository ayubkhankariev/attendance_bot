"""Подсчёт людей на снимке с помощью нейросети YOLO (ultralytics).

Возвращает: количество людей и снимок с нарисованными рамками
(размеченный снимок отправляется оператору в режиме review,
в группу руководителей уходит чистое фото).
"""
from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _load_model(name: str):
    from ultralytics import YOLO  # импорт здесь, чтобы бот работал и без YOLO
    log.info("Загружаю модель %s (при первом запуске скачивается автоматически)...", name)
    return YOLO(name)


def count_people(image_bytes: bytes, model_name: str = "yolov8s.pt",
                 confidence: float = 0.35, *, imgsz: int = 1280,
                 iou: float = 0.5, augment: bool = True) -> tuple[int, bytes]:
    """Вернёт (число людей, JPEG с рамками).

    Параметры imgsz/iou/augment позволяют тонко настраивать качество детекции
    для отдельных аудиторий или слабых камер без изменения глобальных настроек.
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Не удалось прочитать изображение с камеры")

    model = _load_model(model_name)
    result = model.predict(
        img, classes=[0], conf=confidence, verbose=False,
        imgsz=imgsz,
        iou=iou,
        augment=augment,
    )[0]
    count = 0 if result.boxes is None else len(result.boxes)

    # Тонкие рамки без подписей — жирные текстовые плашки закрывали людей на фото
    annotated = result.plot(line_width=1, labels=False)  # BGR с рамками
    ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    annotated_bytes = buf.tobytes() if ok else image_bytes
    return count, annotated_bytes
