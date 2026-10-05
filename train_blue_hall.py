"""Дообучение YOLO для BLUE HALL на датасете из Roboflow.

Запуск:
    python train_blue_hall.py
    python train_blue_hall.py --epochs 80 --base yolov8n.pt

После обучения лучшие веса лежат в
runs/detect/blue_hall/weights/best.pt — скопируйте их в корень проекта
(например blue_hall_yolov8n.pt) и пропишите в config.yaml:

    "BLUE HALL":
      ...
      counting:
        model: "blue_hall_yolov8n.pt"
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="Blue hall.v1i.yolov8/data.yaml")
    parser.add_argument("--base", default="yolo11s.pt", help="базовая модель для дообучения")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8, help="8ГБ RAM без GPU — держим batch небольшим")
    parser.add_argument("--patience", type=int, default=15, help="ранняя остановка без улучшений")
    parser.add_argument("--name", default="blue_hall")
    args = parser.parse_args()

    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        device="cpu",
        project="runs/detect",
        name=args.name,
        exist_ok=True,
    )


if __name__ == "__main__":
    main()
