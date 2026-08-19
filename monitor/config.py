"""Загрузка и проверка конфигурации (config.yaml)."""
from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytz
import yaml

DEFAULT_PERIODS = {
    1: "09:00", 2: "10:30", 3: "12:00", 4: "14:20",
    5: "15:50", 6: "17:20", 7: "18:50", 8: "20:20",
}


def norm_room(name) -> str:
    """Нормализация названия аудитории: 'lab  406' -> 'LAB 406'."""
    return " ".join(str(name).upper().split())


def _parse_hhmm(value: str) -> dt.time:
    h, m = str(value).strip().split(":")
    return dt.time(int(h), int(m))


class Config:
    def __init__(self, path: str | pathlib.Path):
        path = pathlib.Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Не найден файл конфигурации: {path}\n"
                "Скопируйте config.example.yaml в config.yaml и заполните свои данные."
            )
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        tg = raw.get("telegram") or {}
        self.bot_token: str = str(tg.get("bot_token") or "").strip()
        self.target_chat_id = tg.get("target_chat_id")
        self.review_chat_id = tg.get("review_chat_id")
        self.mode: str = str(tg.get("mode") or "review").strip().lower()
        if self.mode not in ("review", "auto"):
            raise ValueError("telegram.mode должен быть 'review' или 'auto'")
        if self.mode == "review" and not self.review_chat_id:
            raise ValueError("Для режима review нужно указать telegram.review_chat_id")

        admins = tg.get("admin_chat_ids")
        if admins:
            # Если указан список администраторов — использовать его
            self.admin_chat_ids: set[int] = {int(x) for x in admins}
        else:
            # Если admin_chat_ids пуст или не указан — пустой набор (доступ для всех)
            self.admin_chat_ids = set()

        self.tz = pytz.timezone(raw.get("timezone") or "Asia/Tashkent")
        self.working_days = set(raw.get("working_days") or [0, 1, 2, 3, 4, 5])

        edu = raw.get("edupage") or {}
        self.school: str = str(edu.get("school") or "ttpu").strip()

        periods_raw = raw.get("periods") or DEFAULT_PERIODS
        self.periods: dict[int, dt.time] = {
            int(k): _parse_hhmm(v) for k, v in periods_raw.items()
        }
        self.check_offset = int(raw.get("check_offset_minutes", 10))
        pcm = raw.get("presence_check_minutes", 5)
        self.presence_check_minutes: int | None = int(pcm) if pcm is not None else None

        dp = raw.get("day_plan_time")
        self.day_plan_time: dt.time | None = _parse_hhmm(dp) if dp else None

        rules = raw.get("rules") or {}
        self.min_students = int(rules.get("min_students", 10))
        self.low_hashtag = str(rules.get("low_hashtag", "#TALABALARSONI"))
        self.empty_hashtag = str(rules.get("empty_hashtag", "#DARSBARBOD"))
        self.assume_teacher = bool(rules.get("assume_teacher_in_count", True))

        counting = raw.get("counting") or {}
        self.counting_enabled = bool(counting.get("enabled", True))
        self.model_name = str(counting.get("model", "yolov8s.pt"))
        self.confidence = float(counting.get("confidence", 0.35))

        self.cameras: dict[str, dict] = {
            norm_room(k): dict(v or {}) for k, v in (raw.get("cameras") or {}).items()
        }
        self.room_aliases: dict[str, str] = {
            norm_room(k): norm_room(v)
            for k, v in (raw.get("room_aliases") or {}).items()
        }
        self.group_sizes: dict[str, int] = {
            str(k).strip().upper(): int(v)
            for k, v in (raw.get("group_sizes") or {}).items()
        }

    # ---------- удобные методы ----------

    def camera_for_room(self, room: str) -> dict | None:
        key = norm_room(room)
        key = self.room_aliases.get(key, key)
        return self.cameras.get(key)

    def check_time(self, period: int) -> dt.time:
        """Время проверки пары = начало пары + check_offset_minutes."""
        start = self.periods[period]
        base = dt.datetime.combine(dt.date(2000, 1, 1), start)
        t = (base + dt.timedelta(minutes=self.check_offset)).time()
        return t

    def presence_check_time(self, period: int) -> dt.time:
        """Время быстрой проверки присутствия = начало пары + presence_check_minutes."""
        start = self.periods[period]
        base = dt.datetime.combine(dt.date(2000, 1, 1), start)
        t = (base + dt.timedelta(minutes=self.presence_check_minutes)).time()
        return t

    def group_total(self, classes: list[str]) -> int | None:
        total = 0
        found = False
        for c in classes:
            size = self.group_sizes.get(str(c).strip().upper())
            if size:
                total += size
                found = True
        return total if found else None


def update_camera_config(path: str | pathlib.Path, room: str, field: str, value: str) -> None:
    """Точечно меняет IP (в url) или пароль камеры в config.yaml,
    сохраняя комментарии и форматирование файла (через ruamel.yaml)."""
    from ruamel.yaml import YAML

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    path = pathlib.Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml_rt.load(f)

    cams = data.get("cameras") or {}
    key = next((k for k in cams if norm_room(k) == norm_room(room)), None)
    if key is None:
        raise KeyError(f"Камера {room!r} не найдена в {path}")

    if field == "url":
        old_url = str(cams[key].get("url") or "")
        if old_url:
            cams[key]["url"] = re.sub(r"://[^/]+", f"://{value}", old_url, count=1)
        else:
            cams[key]["url"] = f"http://{value}/ISAPI/Streaming/channels/101/picture"
    elif field == "password":
        cams[key]["password"] = value
    else:
        raise ValueError(f"Неизвестное поле для правки камеры: {field}")

    with open(path, "w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)
