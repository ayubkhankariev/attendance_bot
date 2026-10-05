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


def _in_ignore_regions(box_xyxy, img_w: int, img_h: int, regions) -> bool:
    """regions — список [x1,y1,x2,y2] в долях ширины/высоты кадра (0..1).
    Срабатывает, если ЦЕНТР рамки детекции попадает в одну из зон."""
    x1, y1, x2, y2 = box_xyxy
    cx, cy = (x1 + x2) / 2 / img_w, (y1 + y2) / 2 / img_h
    for rx1, ry1, rx2, ry2 in regions:
        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
            return True
    return False


def count_people(image_bytes: bytes, model_name: str = "yolov8s.pt",
                 confidence: float = 0.35, *, imgsz: int = 1280,
                 iou: float = 0.5, augment: bool = True,
                 ignore_regions: list | None = None) -> tuple[int, bytes]:
    """Вернёт (число людей, JPEG с рамками).

    Параметры imgsz/iou/augment позволяют тонко настраивать качество детекции
    для отдельных аудиторий или слабых камер без изменения глобальных настроек.

    ignore_regions — фиксированные зоны кадра (доли ширины/высоты 0..1:
    [x1,y1,x2,y2]), которые исключаются из подсчёта и рамок. Нужны для
    статичных ложных срабатываний камеры (надпись/декор в углу кадра,
    который неподвижен и раз за разом ошибочно распознаётся как человек).
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

    if ignore_regions and result.boxes is not None and len(result.boxes):
        img_h, img_w = img.shape[:2]
        keep = [i for i, box in enumerate(result.boxes.xyxy.tolist())
                if not _in_ignore_regions(box, img_w, img_h, ignore_regions)]
        result = result[keep]

    count = 0 if result.boxes is None else len(result.boxes)

    # Тонкие рамки без подписей — жирные текстовые плашки закрывали людей на фото
    annotated = result.plot(line_width=1, labels=False)  # BGR с рамками
    ok, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    annotated_bytes = buf.tobytes() if ok else image_bytes
    return count, annotated_bytes
