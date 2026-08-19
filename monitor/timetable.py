"""Получение публичного расписания с EduPage (aSc Timetables Online).

Используются те же запросы, что делает страница
https://ttpu.edupage.org/timetable/ в браузере:
  1) ttviewer.js  -> список опубликованных расписаний (берём актуальное)
  2) regulartt.js -> полная база: предметы, преподаватели, аудитории, группы, карточки
"""
from __future__ import annotations

import datetime as dt
import logging

import requests

log = logging.getLogger(__name__)

GSH = "00000000"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json; charset=UTF-8",
}


class EdupageError(RuntimeError):
    pass


class EdupageTimetable:
    def __init__(self, school: str):
        self.school = school
        self.base = f"https://{school}.edupage.org"
        self._db_date: dt.date | None = None
        self._db: dict | None = None

    # ---------------- низкий уровень ----------------

    def _rpc(self, script: str, func: str, args) -> dict:
        url = f"{self.base}/timetable/server/{script}?__func={func}"
        try:
            r = requests.post(
                url, json={"__args": args, "__gsh": GSH},
                headers=HEADERS, timeout=40,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise EdupageError(f"EduPage недоступен ({url}): {e}") from e
        if not isinstance(data, dict) or "r" not in data:
            raise EdupageError(f"Неожиданный ответ EduPage: {str(data)[:300]}")
        return data["r"]

    def _pick_timetable_number(self, today: dt.date) -> str:
        r = self._rpc("ttviewer.js", "getTTViewerData", [None, today.year])
        tts = ((r or {}).get("regular") or {}).get("timetables") or []
        best_date, best = None, None
        for t in tts:
            if t.get("hidden"):
                continue
            d = None
            if t.get("datefrom"):
                try:
                    d = dt.date.fromisoformat(str(t["datefrom"])[:10])
                except ValueError:
                    d = None
            if d is not None and d > today:
                continue  # расписание из будущего
            key = d or dt.date.min
            if best is None or key >= (best_date or dt.date.min):
                best_date, best = key, t
        if best is None:
            raise EdupageError("На EduPage не найдено активное опубликованное расписание")
        log.info("Выбрано расписание EduPage: %s (tt_num=%s, c %s)",
                 best.get("text"), best.get("tt_num"), best.get("datefrom"))
        return str(best["tt_num"])

    def _load_db(self, today: dt.date) -> dict:
        num = self._pick_timetable_number(today)
        r = self._rpc("regulartt.js", "regularttGetData", [None, num])
        dbi = (r or {}).get("dbiAccessorRes") or {}
        tables = {}
        for table in dbi.get("tables") or []:
            tables[table.get("id")] = {
                row.get("id"): row for row in (table.get("data_rows") or [])
            }
        for required in ("cards", "lessons", "subjects", "classrooms", "classes", "teachers"):
            if required not in tables:
                raise EdupageError(
                    f"В данных EduPage нет таблицы '{required}'. "
                    "Возможно, формат изменился — нужно обновить парсер."
                )
        return tables

    def _tables(self, date: dt.date) -> dict:
        if self._db is None or self._db_date != date:
            self._db = self._load_db(date)
            self._db_date = date
        return self._db

    # ---------------- высокий уровень ----------------

    @staticmethod
    def _name(row: dict | None, prefer: str = "short") -> str:
        if not row:
            return ""
        other = "name" if prefer == "short" else "short"
        return str(row.get(prefer) or row.get(other) or "").strip()

    def lessons_for(self, date: dt.date) -> list[dict]:
        """Все занятия на дату.

        Возвращает список словарей:
        {period, room, subject, teachers: [..], classes: [..]}
        Одна запись = одна аудитория на одной паре (занятия в одной
        аудитории на одной паре объединяются).
        """
        t = self._tables(date)
        return self._lessons_for_weekday(t, date.weekday())

    def lessons_for_week(self, any_date_in_week: dt.date) -> dict[int, list[dict]]:
        """Занятия на всю неделю (Пн=0..Вс=6), которой принадлежит any_date_in_week.

        Один запрос к EduPage вместо семи — вся неделя уже есть в загруженных таблицах.
        """
        t = self._tables(any_date_in_week)
        return {weekday: self._lessons_for_weekday(t, weekday) for weekday in range(7)}

    def _lessons_for_weekday(self, t: dict, weekday: int) -> list[dict]:
        raw: list[dict] = []
        for card in t["cards"].values():
            days = str(card.get("days") or "")
            if weekday >= len(days) or days[weekday] != "1":
                continue
            lesson = t["lessons"].get(card.get("lessonid"))
            if not lesson:
                continue
            try:
                period = int(card.get("period") or 0)
            except (TypeError, ValueError):
                continue
            if period <= 0:
                continue
            duration = 1
            try:
                duration = max(1, int(lesson.get("durationperiods") or 1))
            except (TypeError, ValueError):
                pass

            room_ids = card.get("classroomids") or lesson.get("classroomids") or []
            rooms = [self._name(t["classrooms"].get(rid)) for rid in room_ids]
            rooms = [r for r in rooms if r]

            subject = self._name(t["subjects"].get(lesson.get("subjectid")), prefer="name")
            teachers = [self._name(t["teachers"].get(tid)) for tid in (lesson.get("teacherids") or [])]
            classes = [self._name(t["classes"].get(cid)) for cid in (lesson.get("classids") or [])]

            for p in range(period, period + duration):
                for room in rooms:
                    raw.append({
                        "period": p,
                        "room": room,
                        "subject": subject or "?",
                        "teachers": [x for x in teachers if x],
                        "classes": [x for x in classes if x],
                    })

        # Объединяем занятия в одной аудитории на одной паре
        merged: dict[tuple, dict] = {}
        for item in raw:
            key = (item["period"], item["room"].upper())
            if key not in merged:
                merged[key] = {
                    "period": item["period"],
                    "room": item["room"],
                    "subjects": [],
                    "teachers": [],
                    "classes": [],
                }
            m = merged[key]
            if item["subject"] not in m["subjects"]:
                m["subjects"].append(item["subject"])
            for x in item["teachers"]:
                if x not in m["teachers"]:
                    m["teachers"].append(x)
            for x in item["classes"]:
                if x not in m["classes"]:
                    m["classes"].append(x)

        out = []
        for m in merged.values():
            out.append({
                "period": m["period"],
                "room": m["room"],
                "subject": " / ".join(m["subjects"]),
                "teachers": m["teachers"],
                "classes": m["classes"],
            })
        out.sort(key=lambda x: (x["period"], x["room"]))
        return out

    def lessons_at(self, date: dt.date, period: int) -> list[dict]:
        return [l for l in self.lessons_for(date) if l["period"] == period]
