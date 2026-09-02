"""TTPU Monitor — автоматическая проверка занятий по камерам.

Запуск бота:            python -m monitor.main
Проверить расписание:   python -m monitor.main --print-timetable [ГГГГ-ММ-ДД]
Проверить камеру:       python -m monitor.main --test-camera "LAB 406"
Другой конфиг:          python -m monitor.main -c путь/к/config.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import functools
import html
import json
import logging
import pathlib
import re
import sys
import tempfile
import uuid
from collections import Counter

from . import i18n
from . import penalties
from .config import Config, norm_room, update_admin_chat_ids, update_camera_config
from .timetable import EdupageTimetable, EdupageError
from .camera import grab_snapshot, CameraError

LANG_FILE = pathlib.Path("lang_prefs.json")

log = logging.getLogger("monitor")

# Пара длится 80 минут (по расписанию TTPU), независимо от длины перерыва до следующей.
LESSON_DURATION_MINUTES = 80

# Если фото в режиме review осталось без вашего решения (✅/⏭) дольше этого срока —
# бот сам забывает о нём, чтобы не копить фото в памяти неделями.
PENDING_MAX_AGE_HOURS = 7 * 24
MASTER_ADMIN_ID = 348804943


def current_period(cfg: Config, now: dt.datetime) -> int | None:
    """Номер пары, идущей прямо сейчас, или None (перерыв/до начала занятий)."""
    t = now.time()
    for period, start in cfg.periods.items():
        end = (dt.datetime.combine(dt.date.min, start)
               + dt.timedelta(minutes=LESSON_DURATION_MINUTES)).time()
        if start <= t <= end:
            return period
    return None


def _teacher_matches(query: str, teacher: str) -> bool:
    """Сравнение по фамилии/токенам без учёта регистра и сокращений вида 'KH.KHAMIDULLA'."""
    norm = lambda s: [w for w in re.sub(r"[^A-Za-zА-Яа-яЁё]+", " ", s.upper()).split() if len(w) >= 3]
    q_tokens, t_tokens = norm(query), norm(teacher)
    return any(qt in tt or tt in qt for qt in q_tokens for tt in t_tokens)


def _resolved_room(cfg: Config, room: str) -> str:
    key = norm_room(room)
    return cfg.room_aliases.get(key, key)


# ============================================================
#  Язык интерфейса (хранится в lang_prefs.json — переживает перезапуск бота)
# ============================================================

def _load_lang_prefs() -> dict[int, str]:
    if LANG_FILE.exists():
        try:
            return {int(k): v for k, v in json.loads(LANG_FILE.read_text(encoding="utf-8")).items()}
        except Exception:
            log.exception("Не удалось прочитать %s", LANG_FILE)
    return {}


def _save_lang_prefs(prefs: dict[int, str]) -> None:
    try:
        LANG_FILE.write_text(json.dumps(prefs), encoding="utf-8")
    except Exception:
        log.exception("Не удалось сохранить %s", LANG_FILE)


def get_lang(app, chat_id) -> str:
    return app.bot_data.setdefault("lang_prefs", _load_lang_prefs()).get(chat_id, i18n.DEFAULT_LANG)


def set_lang(app, chat_id, lang: str) -> None:
    prefs = app.bot_data.setdefault("lang_prefs", _load_lang_prefs())
    prefs[chat_id] = lang
    _save_lang_prefs(prefs)


def admin_only(handler):
    """Ограничивает команду/кнопку списком telegram.admin_chat_ids.
    /id — единственное исключение (нужна, чтобы вообще узнать свой chat_id).
    Если admin_chat_ids пуст — доступ для всех."""
    @functools.wraps(handler)
    async def wrapper(update, context):
        cfg: Config = context.application.bot_data["cfg"]
        chat_id = update.effective_chat.id
        # Если список администраторов не пуст, проверяем доступ
        if cfg.admin_chat_ids and chat_id not in cfg.admin_chat_ids and not _is_master_admin(chat_id):
            lang = get_lang(context.application, chat_id)
            await update.effective_message.reply_text(
                i18n.t(lang, "msg_access_denied", chat_id=chat_id)
            )
            return
        return await handler(update, context)
    return wrapper


def _is_master_admin(chat_id: int) -> bool:
    return chat_id == MASTER_ADMIN_ID


# ============================================================
#  Формирование подписи к фото
# ============================================================

def base_lines(lesson: dict) -> list[str]:
    """Строки: предмет / ПРЕПОДАВАТЕЛЬ / аудитория / группы."""
    lines = [lesson["subject"]]
    if lesson["teachers"]:
        lines.append(", ".join(t.upper() for t in lesson["teachers"]))
    lines.append(lesson["room"])
    if lesson["classes"]:
        lines.append(" / ".join(lesson["classes"]))
    return [x for x in lines if x]


def final_caption(cfg: Config, lesson: dict, students: int) -> str:
    """Итоговая подпись с хештегами по правилам."""
    lines = base_lines(lesson)
    if students <= 0:
        lines.append(cfg.empty_hashtag)
    elif students < cfg.min_students:
        total = cfg.group_total(lesson["classes"])
        lines.append(f"{cfg.low_hashtag} {students}/{total if total else '?'}")
    return "\n".join(lines)


def _detect_violation_type(cfg: Config, caption: str) -> str | None:
    """ZAMENA камерой не подтвердить (нужен человек) — только TALABALARSONI/DARSBARBOD,
    и то лишь если итоговый хештег реально попал в отправленный текст (учитывает
    правки ➖/➕ и ручное редактирование подписи)."""
    if cfg.empty_hashtag and cfg.empty_hashtag in caption:
        return "DARSBARBOD"
    if cfg.low_hashtag and cfg.low_hashtag in caption:
        return "TALABALARSONI"
    return None


async def _maybe_log_violation(app, lesson: dict, period: int, students: int,
                                date: dt.date, caption: str, msg) -> None:
    cfg: Config = app.bot_data["cfg"]
    vtype = _detect_violation_type(cfg, caption)
    if vtype is None:
        return
    total = None
    if vtype == "TALABALARSONI":
        total = cfg.group_total(lesson["classes"])
    else:
        students = None
    try:
        link = msg.link
    except Exception:
        link = None
    
    # Проверка на дублирование в течение 5 минут
    records = penalties.all_records(app)
    duplicate = penalties.find_duplicate_within_time(
        records, date, period, 
        ", ".join(t.upper() for t in lesson["teachers"]) or "-",
        lesson["classes"],
        minutes_threshold=5
    )
    
    if duplicate:
        # Есть дубликат - обновляем старый пост (заменяем на новый)
        # Удаляем старый пост из группы и добавляем новый
        if duplicate.get("message_id") and duplicate.get("message_chat_id"):
            try:
                await app.bot.delete_message(
                    chat_id=duplicate["message_chat_id"],
                    message_id=duplicate["message_id"]
                )
            except Exception as e:
                log.warning("Не удалось удалить старый пост: %s", e)
        
        # Обновляем данные штрафа
        penalties.update(
            app,
            duplicate["id"],
            students=students,
            message_id=msg.message_id,
            message_chat_id=cfg.target_chat_id,
            link=link,
            created=dt.datetime.now().isoformat(timespec="seconds"),
        )
        log.info("Дубликат урока найден - пост обновлён: %s пара %s", 
                lesson["room"], period)
        return
    
    # Нет дубликата - добавляем новый штраф
    penalties.add(
        app,
        date=date,
        period=period,
        teacher=", ".join(t.upper() for t in lesson["teachers"]) or "-",
        subject=lesson["subject"],
        groups=lesson["classes"],
        vtype=vtype,
        students=students,
        total=total,
        link=link,
        message_id=msg.message_id,
        message_chat_id=cfg.target_chat_id,
    )


def detected_to_students(cfg: Config, detected: int) -> int:
    """Найдено людей на фото -> предполагаемое число студентов."""
    if detected <= 0:
        return 0
    if cfg.assume_teacher:
        return max(detected - 1, 0)
    return detected


def camera_counting_settings(cfg: Config, cam: dict | None) -> dict:
    """Параметры детекции для конкретной камеры или глобального конфига."""
    room_cfg = (cam or {}).get("counting") or {}
    return {
        "model_name": str(room_cfg.get("model") or cfg.model_name),
        "confidence": float(room_cfg.get("confidence", cfg.confidence)),
        "imgsz": int(room_cfg.get("imgsz", 1280)),
        "iou": float(room_cfg.get("iou", 0.5)),
        "augment": bool(room_cfg.get("augment", True)),
    }


# ============================================================
#  Основная логика проверки одной пары
# ============================================================

async def run_check(app, period: int, date: dt.date | None = None,
                    announce_chat=None) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    date = date or dt.datetime.now(cfg.tz).date()

    notify_chat = announce_chat or (cfg.review_chat_id[0] if isinstance(cfg.review_chat_id, list) else cfg.review_chat_id) or cfg.target_chat_id

    try:
        lessons = await asyncio.to_thread(tt.lessons_at, date, period)
    except EdupageError as e:
        log.error("Расписание: %s", e)
        await app.bot.send_message(notify_chat, f"⚠️ Не удалось получить расписание: {e}")
        return

    if not lessons:
        log.info("Пара %s: занятий нет", period)
        if announce_chat:
            await app.bot.send_message(announce_chat, f"Пара {period}: занятий в расписании нет.")
        return

    checked = skipped = 0
    for lesson in lessons:
        cam = cfg.camera_for_room(lesson["room"])
        if not cam:
            skipped += 1
            log.info("Пара %s, %s: камера не настроена — пропуск", period, lesson["room"])
            continue
        checked += 1
        try:
            await process_lesson(app, lesson, cam, period, requester_chat_id=announce_chat)
        except Exception as e:  # noqa: BLE001 — не роняем весь цикл из-за одной камеры
            log.exception("Ошибка при проверке %s", lesson["room"])
            try:
                await app.bot.send_message(
                    notify_chat,
                    f"⚠️ Пара {period}, {lesson['room']} ({lesson['subject']}): "
                    f"не удалось проверить — {e}",
                )
            except Exception:
                pass

    log.info("Пара %s: проверено %s, без камеры %s", period, checked, skipped)
    if announce_chat and checked == 0:
        await app.bot.send_message(
            announce_chat,
            f"Пара {period}: занятия есть ({len(lessons)}), но ни для одной аудитории "
            "не настроена камера в config.yaml.",
        )


async def process_lesson(app, lesson: dict, cam: dict, period: int, requester_chat_id=None) -> None:
    cfg: Config = app.bot_data["cfg"]

    photo = await asyncio.to_thread(grab_snapshot, cam)

    detected = None
    annotated = photo
    if cfg.counting_enabled:
        from . import people_counter
        counting = camera_counting_settings(cfg, cam)
        detected, annotated = await asyncio.to_thread(
            people_counter.count_people,
            photo,
            counting["model_name"],
            counting["confidence"],
            imgsz=counting["imgsz"],
            iou=counting["iou"],
            augment=counting["augment"],
        )

    students = detected_to_students(cfg, detected) if detected is not None else 0
    caption = final_caption(cfg, lesson, students)
    today = dt.datetime.now(cfg.tz).date()

    if cfg.mode == "auto" and cfg.counting_enabled:
        try:
            msg = await app.bot.send_photo(cfg.target_chat_id, photo=photo, caption=caption)
        except Exception:
            log.exception("Не удалось отправить фото в группу руководителей: %s / %s",
                          lesson["room"], lesson["subject"])
            return
        await _maybe_log_violation(app, lesson, period, students, today, caption, msg)
        log.info("Отправлено в группу: %s / %s (людей: %s)",
                 lesson["room"], lesson["subject"], detected)
        return

    # ---- режим review: отправляем оператору с кнопками ----
    # Если проверку запросил конкретный пользователь — отправляем ему,
    # иначе отправляем в review_chat_id (автоматическая плановая проверка)
    review_chat_id = requester_chat_id or (cfg.review_chat_id[0] if isinstance(cfg.review_chat_id, list) else cfg.review_chat_id)
    
    pid = uuid.uuid4().hex[:12]
    item = {
        "photo": photo,
        "lesson": lesson,
        "period": period,
        "students": students,
        "detected": detected,
        "created": dt.datetime.now(cfg.tz),
        "date": today,
        "custom_caption": None,
    }
    app.bot_data.setdefault("pending", {})[pid] = item

    info = f"🕘 Пара {period} • {lesson['room']}"
    if detected is not None:
        info += f"\n🤖 Найдено людей на фото: {detected}"
        if cfg.assume_teacher and detected > 0:
            info += f" (студентов: {students}, 1 считаем преподавателем)"
    review_caption = final_caption(cfg, lesson, students) + "\n――――――\n" + info

    msg = await app.bot.send_photo(
        review_chat_id,
        photo=annotated,
        caption=review_caption,
        reply_markup=_keyboard(pid, item),
    )
    item["review_chat"] = msg.chat_id
    item["review_msg"] = msg.message_id


def _current_caption(cfg: Config, item: dict) -> str:
    custom = item.get("custom_caption")
    return custom if custom is not None else final_caption(cfg, item["lesson"], item["students"])


def _keyboard(pid: str, item: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if item.get("custom_caption") is not None:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Отправить", callback_data=f"send:{pid}"),
                InlineKeyboardButton("↩️ Сбросить правку", callback_data=f"reset:{pid}"),
            ],
            [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip:{pid}")],
        ])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"dec:{pid}"),
            InlineKeyboardButton(f"👥 {item['students']}", callback_data=f"noop:{pid}"),
            InlineKeyboardButton("➕", callback_data=f"inc:{pid}"),
        ],
        [
            InlineKeyboardButton("✏️ Изменить текст", callback_data=f"edit:{pid}"),
            InlineKeyboardButton("📷 Другая аудитория", callback_data=f"roompick:{pid}"),
        ],
        [
            InlineKeyboardButton("✅ Отправить", callback_data=f"send:{pid}"),
            InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip:{pid}"),
        ],
    ])


def _room_pick_keyboard(pid: str, lang: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rooms = ALL_ROOM_NAMES
    buttons = [InlineKeyboardButton(r, callback_data=f"roomsel:{pid}:{r}") for r in rooms]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(i18n.t(lang, "btn_cancel"), callback_data=f"roomcancel:{pid}")])
    return InlineKeyboardMarkup(rows)


# ============================================================
#  Обработчики Telegram
# ============================================================

@admin_only
async def on_callback(update, context):
    cfg: Config = context.application.bot_data["cfg"]
    q = update.callback_query
    action, _, pid = (q.data or "").partition(":")
    pending: dict = context.application.bot_data.setdefault("pending", {})
    item = pending.get(pid)

    if item is None:
        await q.answer("Эта проверка уже обработана или устарела", show_alert=True)
        return

    if action == "noop":
        await q.answer(f"Студентов: {item['students']}")
        return

    if action in ("inc", "dec"):
        item["students"] = max(0, item["students"] + (1 if action == "inc" else -1))
        caption = final_caption(cfg, item["lesson"], item["students"])
        info = f"🕘 Пара {item['period']} • {item['lesson']['room']}"
        if item["detected"] is not None:
            info += f"\n🤖 Найдено людей на фото: {item['detected']}"
        await q.edit_message_caption(
            caption=caption + "\n――――――\n" + info,
            reply_markup=_keyboard(pid, item),
        )
        await q.answer()
        return

    if action == "skip":
        pending.pop(pid, None)
        await q.edit_message_caption(
            caption=(q.message.caption or "") + "\n\n⏭ Пропущено, в группу не отправлено."
        )
        await q.answer("Пропущено")
        return

    if action == "send":
        caption = _current_caption(cfg, item)
        try:
            msg = await context.bot.send_photo(cfg.target_chat_id, photo=item["photo"], caption=caption)
        except Exception as e:
            log.exception("Не удалось отправить фото в группу руководителей (pid=%s)", pid)
            await q.answer(f"⚠️ Ошибка отправки: {e}", show_alert=True)
            return
        await _maybe_log_violation(
            context.application, item["lesson"], item["period"], item["students"],
            item.get("date") or dt.datetime.now(cfg.tz).date(), caption, msg,
        )
        pending.pop(pid, None)
        await q.edit_message_caption(caption=caption + "\n\n✅ Отправлено в группу руководителей.")
        await q.answer("Отправлено ✅")
        return

    if action == "edit":
        app = context.application
        chat_id = q.message.chat_id
        app.bot_data.setdefault("awaiting_caption_edit", {})[chat_id] = pid
        lang = get_lang(app, chat_id)
        current = _current_caption(cfg, item)
        await q.answer()
        # Telegram не даёт боту заранее вписать текст в поле ввода — присылаем текущий
        # текст моноширинным блоком (<code>): в большинстве клиентов достаточно один раз
        # тапнуть по нему, чтобы скопировать, — быстрее, чем зажимать и выбирать "Copy".
        await q.message.reply_text(
            i18n.t(lang, "msg_current_caption_is") + "\n\n<code>" + html.escape(current) + "</code>",
            parse_mode="HTML",
        )
        await q.message.reply_text(i18n.t(lang, "msg_enter_new_caption"))
        return

    if action == "roompick":
        lang = get_lang(context.application, q.message.chat_id)
        await q.answer()
        await q.edit_message_reply_markup(reply_markup=_room_pick_keyboard(pid, lang))
        return

    if action == "roomcancel":
        await q.answer()
        await q.edit_message_reply_markup(reply_markup=_keyboard(pid, item))
        return

    if action == "reset":
        item["custom_caption"] = None
        caption = _current_caption(cfg, item)
        info = f"🕘 Пара {item['period']} • {item['lesson']['room']}"
        if item["detected"] is not None:
            info += f"\n🤖 Найдено людей на фото: {item['detected']}"
        await q.edit_message_caption(
            caption=caption + "\n――――――\n" + info,
            reply_markup=_keyboard(pid, item),
        )
        await q.answer()
        return

    await q.answer()


async def apply_caption_edit(app, chat_id, pid: str, text: str) -> None:
    pending: dict = app.bot_data.setdefault("pending", {})
    item = pending.get(pid)
    lang = get_lang(app, chat_id)
    if item is None:
        await app.bot.send_message(chat_id, "Эта проверка уже обработана или устарела.")
        return
    item["custom_caption"] = text
    try:
        await app.bot.edit_message_caption(
            chat_id=item["review_chat"], message_id=item["review_msg"],
            caption=text, reply_markup=_keyboard(pid, item),
        )
    except Exception:
        log.exception("Не удалось применить правку подписи (pid=%s)", pid)
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_caption_updated"))


@admin_only
async def on_room_pick_select(update, context):
    """«📷 Другая аудитория» на карточке review: пересъёмка фото из другой
    аудитории — на случай если пару перенесли в другой кабинет технически."""
    app = context.application
    cfg: Config = app.bot_data["cfg"]
    q = update.callback_query
    _, pid, room = (q.data or "").split(":", 2)
    pending: dict = app.bot_data.setdefault("pending", {})
    item = pending.get(pid)
    if item is None:
        await q.answer("Эта проверка уже обработана или устарела", show_alert=True)
        return

    cam = cfg.camera_for_room(room)
    if not cam:
        await q.answer(f"Камера для {room!r} не настроена", show_alert=True)
        return

    await q.answer("Снимаю...")
    try:
        photo = await asyncio.to_thread(grab_snapshot, cam)
    except CameraError as e:
        await q.answer(f"⚠️ {e}", show_alert=True)
        return

    detected = None
    annotated = photo
    if cfg.counting_enabled:
        from . import people_counter
        counting = camera_counting_settings(cfg, cam)
        detected, annotated = await asyncio.to_thread(
            people_counter.count_people,
            photo,
            counting["model_name"],
            counting["confidence"],
            imgsz=counting["imgsz"],
            iou=counting["iou"],
            augment=counting["augment"],
        )

    item["lesson"] = dict(item["lesson"], room=norm_room(room))
    item["photo"] = photo
    item["detected"] = detected
    item["students"] = detected_to_students(cfg, detected) if detected is not None else 0
    item["custom_caption"] = None

    info = f"🕘 Пара {item['period']} • {item['lesson']['room']}"
    if detected is not None:
        info += f"\n🤖 Найдено людей на фото: {detected}"
        if cfg.assume_teacher and detected > 0:
            info += f" (студентов: {item['students']}, 1 считаем преподавателем)"
    caption = final_caption(cfg, item["lesson"], item["students"]) + "\n――――――\n" + info

    from telegram import InputMediaPhoto
    lang = get_lang(app, q.message.chat_id)
    try:
        await context.bot.edit_message_media(
            chat_id=item["review_chat"], message_id=item["review_msg"],
            media=InputMediaPhoto(media=annotated, caption=caption),
            reply_markup=_keyboard(pid, item),
        )
    except Exception:
        log.exception("Не удалось заменить фото аудитории (pid=%s)", pid)
    await q.message.reply_text(i18n.t(lang, "msg_room_changed", room=item["lesson"]["room"]))


@admin_only
async def on_check_room_button(update, context):
    """Кнопка «👥 Посчитать и отправить» под фото из раздела Камеры-Аудитории —
    ручной разовый запуск полного цикла (подсчёт людей + кнопки review) для одной аудитории."""
    app = context.application
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    q = update.callback_query
    _, period_str, room = (q.data or "").split(":", 2)
    period = int(period_str)

    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.answer("Считаю...")

    now = dt.datetime.now(cfg.tz)
    try:
        lessons = await asyncio.to_thread(tt.lessons_at, now.date(), period)
    except EdupageError as e:
        await q.message.reply_text(f"⚠️ {e}")
        return
    target = _resolved_room(cfg, room)
    lesson = next((l for l in lessons if _resolved_room(cfg, l["room"]) == target), None)
    if lesson is None:
        await q.message.reply_text("Урок уже закончился или не найден в расписании.")
        return
    cam = cfg.camera_for_room(room)
    if not cam:
        lang = get_lang(app, q.message.chat_id)
        await q.message.reply_text(i18n.t(lang, "msg_no_camera_for_lesson"))
        return
    await process_lesson(app, lesson, cam, period, requester_chat_id=q.message.chat_id)


async def cmd_id(update, context):
    chat = update.effective_chat
    await update.effective_message.reply_text(
        f"ID этого чата: `{chat.id}`", parse_mode="Markdown"
    )


@admin_only
async def cmd_start(update, context):
    lang = get_lang(context.application, update.effective_chat.id)
    await update.effective_message.reply_text(
        i18n.t(lang, "msg_welcome"), parse_mode="HTML"
    )
    await cmd_menu(update, context)


async def send_plan(app, chat_id) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    date = dt.datetime.now(cfg.tz).date()
    try:
        lessons = await asyncio.to_thread(tt.lessons_for, date)
    except EdupageError as e:
        await app.bot.send_message(chat_id, f"⚠️ {e}")
        return
    if not lessons:
        await app.bot.send_message(chat_id, f"На {date} занятий в расписании нет.")
        return
    lines = [f"📅 План на {date} (проверка через {cfg.check_offset} мин после начала):"]
    cur = None
    for l in lessons:
        if l["period"] != cur:
            cur = l["period"]
            start = cfg.periods.get(cur)
            check = cfg.check_time(cur) if cur in cfg.periods else None
            lines.append(f"\n— Пара {cur}"
                         + (f" ({start.strftime('%H:%M')}, проверка {check.strftime('%H:%M')})"
                            if start else ""))
        has_cam = "✅" if cfg.camera_for_room(l["room"]) else "🚫 нет камеры"
        teachers = ", ".join(t.upper() for t in l["teachers"])
        lines.append(f"  {l['room']}: {l['subject']} | {teachers} [{' / '.join(l['classes'])}] {has_cam}")
    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await app.bot.send_message(chat_id, text[i:i + 3800])


async def send_week_plan(app, chat_id) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    today = dt.datetime.now(cfg.tz).date()
    monday = today - dt.timedelta(days=today.weekday())
    try:
        week = await asyncio.to_thread(tt.lessons_for_week, monday)
    except EdupageError as e:
        await app.bot.send_message(chat_id, f"⚠️ {e}")
        return

    day_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    lines = [f"🗓 Расписание на неделю ({monday} — {monday + dt.timedelta(days=5)}):"]
    for weekday in sorted(cfg.working_days):
        lessons = week.get(weekday, [])
        date_d = monday + dt.timedelta(days=weekday)
        lines.append(f"\n=== {day_names[weekday]} {date_d} ===")
        if not lessons:
            lines.append("  занятий нет")
            continue
        cur = None
        for l in lessons:
            if l["period"] != cur:
                cur = l["period"]
                start = cfg.periods.get(cur)
                lines.append(f"--- Пара {cur}" + (f" ({start.strftime('%H:%M')})" if start else ""))
            has_cam = "✅" if cfg.camera_for_room(l["room"]) else "🚫"
            teachers = ", ".join(t.upper() for t in l["teachers"])
            lines.append(f"  {l['room']}: {l['subject']} | {teachers} [{' / '.join(l['classes'])}] {has_cam}")

    text = "\n".join(lines)
    for i in range(0, len(text), 3800):
        await app.bot.send_message(chat_id, text[i:i + 3800])


async def send_camera_health(app, chat_id) -> None:
    """Живая проверка всех камер (не просто список из конфига)."""
    cfg: Config = app.bot_data["cfg"]
    if not cfg.cameras:
        await app.bot.send_message(chat_id, "В config.yaml не настроено ни одной камеры.")
        return
    await app.bot.send_message(chat_id, f"Проверяю {len(cfg.cameras)} камер, подождите...")

    async def check_one(room, cam):
        try:
            await asyncio.to_thread(grab_snapshot, cam)
            return room, None
        except Exception as e:
            return room, str(e)

    results = await asyncio.gather(*(check_one(r, c) for r, c in cfg.cameras.items()))
    results.sort(key=lambda r: r[0])
    bad = [(room, err) for room, err in results if err]
    lines = [f"✅ Работают: {len(results) - len(bad)}/{len(results)}"]
    if bad:
        lines.append("\n🚫 Не отвечают:")
        lines += [f"• {room} — {err}" for room, err in bad]
    await app.bot.send_message(chat_id, "\n".join(lines))


async def send_room_photo(app, chat_id, room: str) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]

    cam = cfg.camera_for_room(room)
    if not cam:
        await app.bot.send_message(
            chat_id,
            f"Камера для аудитории {room!r} не настроена.\n"
            f"Настроены: {', '.join(sorted(cfg.cameras)) or '(нет)'}",
        )
        return

    try:
        photo = await asyncio.to_thread(grab_snapshot, cam)
    except CameraError as e:
        await app.bot.send_message(chat_id, f"⚠️ Не удалось получить фото с камеры: {e}")
        return

    now = dt.datetime.now(cfg.tz)
    period = current_period(cfg, now)
    caption = None
    found_lesson = False
    if period is not None:
        try:
            lessons = await asyncio.to_thread(tt.lessons_at, now.date(), period)
        except EdupageError:
            lessons = []
        target = _resolved_room(cfg, room)
        for l in lessons:
            if _resolved_room(cfg, l["room"]) == target:
                caption = "\n".join(base_lines(l))
                found_lesson = True
                break
    if not caption:
        caption = f"{norm_room(room)}\nВ данный момент урок не проводится."

    kb = None
    if found_lesson and cfg.counting_enabled:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        lang = get_lang(app, chat_id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            i18n.t(lang, "btn_check_room"), callback_data=f"checkroom:{period}:{norm_room(room)}"
        )]])
    await app.bot.send_photo(chat_id, photo=photo, caption=caption, reply_markup=kb)


async def send_teacher_photo(app, chat_id, query: str) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]

    now = dt.datetime.now(cfg.tz)
    period = current_period(cfg, now)
    if period is None:
        await app.bot.send_message(chat_id, f"У преподавателя «{query}» сейчас нету урока (перерыв).")
        return

    try:
        lessons = await asyncio.to_thread(tt.lessons_at, now.date(), period)
    except EdupageError as e:
        await app.bot.send_message(chat_id, f"⚠️ {e}")
        return

    matches = [l for l in lessons if any(_teacher_matches(query, t) for t in l["teachers"])]
    if not matches:
        await app.bot.send_message(chat_id, f"У преподавателя «{query}» сейчас нету урока.")
        return

    for lesson in matches:
        info = "\n".join(base_lines(lesson))
        cam = cfg.camera_for_room(lesson["room"])
        if not cam:
            await app.bot.send_message(chat_id, info + "\n\n(камера для этой аудитории не настроена)")
            continue
        try:
            photo = await asyncio.to_thread(grab_snapshot, cam)
        except CameraError as e:
            await app.bot.send_message(chat_id, info + f"\n\n⚠️ Не удалось получить фото: {e}")
            continue
        await app.bot.send_photo(chat_id, photo=photo, caption=info)


# ============================================================
#  Кнопочное меню (reply-клавиатура — кнопки снизу под полем ввода)
#
#  Все состояния меню и кнопки идентифицируются языконезависимыми id
#  (например "schedule", "floor_a4") — отображаемый текст кнопки для
#  них берётся из i18n.t(lang, f"btn_{id}") в момент отрисовки, поэтому
#  один и тот же код работает сразу на RU/EN/UZ. Аудитории и имена
#  преподавателей — данные, а не интерфейс, поэтому не переводятся.
# ============================================================

# Аудитории по этажам/спискам (ключ = id состояния меню).
# Названия должны совпадать с ключами cameras в config.yaml.
ROOMS_BY_STATE: dict[str, list[str]] = {
    "floor_a4": ["LAB 401", "LAB 403", "LAB 404", "LAB 405", "LAB 406", "LAB 407",
                 "402AB", "403AB", "404AB"],
    "floor_a3": ["301", "303", "304", "305", "306", "307", "302AB", "303AB", "305AB"],
    "floor_a2": ["201", "203", "204", "205", "206", "207"],
    "floor_a1": ["105", "107", "BLUE HALL", "GREEN HALL", "101 CHEM LAB"],
    # Здание C и Mechatronics: IP камер ещё не переданы — кнопки уже работают,
    # send_room_photo просто ответит "камера не настроена", пока их не добавят в config.yaml.
    "floor_c4": ["C401", "C402", "C403", "C404"],
    "floor_c3": ["C301", "C302", "C303", "C304"],
    "floor_c2": ["C201", "C202", "C203", "C204"],
    "floor_c1": ["C101", "C102"],
    "building_b": ["GREY HALL", "YELLOW HALL", "B1 AUDITORIUM"],
    "building_mech": ["SPECIAL LAB #1", "SPECIAL LAB #2", "SPECIAL LAB #3"],
}
# Здания B и Mechatronics — плоский список без этажей.
FLAT_BUILDING_STATES = {"building_b", "building_mech"}

ALL_ROOM_NAMES = sorted({r for rooms in ROOMS_BY_STATE.values() for r in rooms})
# Отдельный "виртуальный этаж" для настройки камер — включает все аудитории сразу.
ROOMS_BY_STATE["camera_settings"] = ALL_ROOM_NAMES
# У списка для настройки камер нет кнопки "ВСЕ" (выбор там = редактирование, не фото).
NO_ALL_BUTTON_STATES = {"camera_settings"}

# item: (id, kind); kind "state" — переход в подменю с этим id, "action" — вызов обработчика
STATE_ITEMS: dict[str, list[tuple[str, str]]] = {
    "main": [("schedule", "state"), ("cameras", "state"),
             ("teachers", "state"), ("penalties", "state"), ("settings", "state")],
    "schedule": [("week_schedule", "action"), ("day_schedule", "action"), ("report", "state")],
    "cameras": [("building_a", "state"),
                ("building_b", "state"), ("building_c", "state"), ("building_mech", "state"), ("check_cams", "action")],
    "building_a": [("floor_a4", "state"), ("floor_a3", "state"),
                   ("floor_a2", "state"), ("floor_a1", "state")],
    "building_c": [("floor_c4", "state"), ("floor_c3", "state"),
                   ("floor_c2", "state"), ("floor_c1", "state")],
    "teachers": [("teacher_search", "action"), ("teacher_list", "state")],
    "penalties": [("penalty_period", "action"), ("penalty_add", "action"), ("penalty_delete", "action"), ("manage_posts", "action")],
    "settings": [("lang", "state"), ("camera_settings", "state"),
                  ("admin_ids", "state"), ("health_check", "action")],
    "admin_ids": [("admin_add", "action"), ("admin_remove", "action")],
}

STATE_PARENT: dict[str, str] = {
    "schedule": "main", "cameras": "main", "teachers": "main", "settings": "main",
    "penalties": "main",
    "building_a": "cameras", "building_b": "cameras",
    "building_c": "cameras", "building_mech": "cameras",
    "floor_a4": "building_a", "floor_a3": "building_a",
    "floor_a2": "building_a", "floor_a1": "building_a",
    "floor_c4": "building_c", "floor_c3": "building_c",
    "floor_c2": "building_c", "floor_c1": "building_c",
    "teacher_list": "teachers", "lang": "settings",
    "camera_settings": "settings", "admin_ids": "settings", "report": "schedule",
}

BUILDING_TITLE_ID = {  # для заголовка "{здание} — выберите..."
    "building_a": "btn_building_a", "building_c": "btn_building_c",
    "building_b": "btn_building_b", "building_mech": "btn_building_mech",
}

_LANG_CODE_BY_NAME = {name: code for code, name in i18n.LANGUAGES.items()}


def _btn_label(id_: str, lang: str) -> str:
    """Подпись кнопки по id. Этажи (floor_a4, floor_c1...) намеренно используют
    ОДИН общий перевод "btn_floor_N" на все здания — экономит переводы, а
    неоднозначность ("4 этаж" в здании A и в здании C") снимается тем, что
    кнопка ищется среди пунктов ТЕКУЩЕГО раздела меню (см. _resolve_menu_id),
    а не по глобальному словарю "подпись -> id"."""
    if id_.startswith("floor_"):
        return i18n.t(lang, f"btn_floor_{id_[-1]}")
    return i18n.t(lang, f"btn_{id_}")


def _resolve_menu_id(cur: str, lang: str, text: str, chat_id: int | None = None) -> str | None:
    """Ищет нажатую кнопку среди пунктов ТЕКУЩЕГО состояния меню (state-scoped) —
    так одинаковые подписи в разных разделах (например "4 этаж" для A и C) не путаются."""
    for id_, _kind in STATE_ITEMS.get(cur, []):
        if id_ == "admin_ids" and not _is_master_admin(chat_id or 0):
            continue
        if _btn_label(id_, lang) == text:
            return id_
    return None


def _title(state: str, lang: str) -> str:
    if state in BUILDING_TITLE_ID:
        key = "title_building_flat" if state in FLAT_BUILDING_STATES else "title_building"
        return i18n.t(lang, key, building=i18n.t(lang, BUILDING_TITLE_ID[state]))
    if state.startswith("floor_"):
        return i18n.t(lang, "title_floor", floor=_btn_label(state, lang))
    if state == "camera_settings":
        return i18n.t(lang, "title_camera_settings")
    return i18n.t(lang, f"title_{state}")


def _kb_rows(state: str, lang: str, chat_id: int | None = None) -> list[list[str]]:
    if state == "lang":
        rows = [[name] for name in i18n.LANGUAGES.values()]
        rows.append([i18n.t(lang, "btn_back")])
        return rows
    if state == "report":
        nums = [i18n.t(lang, "btn_period", n=n) for n in range(1, 9)]
        rows = [nums[i:i + 2] for i in range(0, len(nums), 2)]
        rows.append([i18n.t(lang, "btn_back")])
        return rows
    if state in ROOMS_BY_STATE:
        rooms = ROOMS_BY_STATE[state]
        rows = [rooms[i:i + 2] for i in range(0, len(rooms), 2)]
        if state not in NO_ALL_BUTTON_STATES:
            rows.append([i18n.t(lang, "btn_all")])
        rows.append([i18n.t(lang, "btn_back")])
        return rows
    items = STATE_ITEMS[state]
    if state == "settings" and not _is_master_admin(chat_id or 0):
        items = [(id_, kind) for id_, kind in items if id_ != "admin_ids"]
    labels = [_btn_label(id_, lang) for id_, _ in items]
    rows = [labels[i:i + 2] for i in range(0, len(labels), 2)]
    if state != "main":
        rows.append([i18n.t(lang, "btn_back")])
    return rows


def _reply_markup(state: str, lang: str, chat_id: int | None = None):
    from telegram import ReplyKeyboardMarkup
    return ReplyKeyboardMarkup(_kb_rows(state, lang, chat_id), resize_keyboard=True)


async def _goto(app, chat_id, state: str) -> None:
    lang = get_lang(app, chat_id)
    app.bot_data.setdefault("nav", {})[chat_id] = state
    if state == "admin_ids":
        admin_ids = sorted(app.bot_data["cfg"].admin_chat_ids)
        ids_text = ", ".join(str(admin_id) for admin_id in admin_ids) or "—"
        text = i18n.t(lang, "title_admin_ids") + "\n\n" + i18n.t(lang, "msg_admin_ids", ids=ids_text)
        await app.bot.send_message(chat_id, text, reply_markup=_reply_markup(state, lang, chat_id))
        return
    await app.bot.send_message(chat_id, _title(state, lang), reply_markup=_reply_markup(state, lang, chat_id))


async def _start_admin_id_change(app, chat_id: int, action: str) -> None:
    lang = get_lang(app, chat_id)
    app.bot_data.setdefault("awaiting_admin_id", {})[chat_id] = action
    key = "msg_enter_admin_id_add" if action == "add" else "msg_enter_admin_id_remove"
    await app.bot.send_message(chat_id, i18n.t(lang, key))


async def _apply_admin_id_change(app, chat_id: int, text: str) -> None:
    lang = get_lang(app, chat_id)
    action = app.bot_data.setdefault("awaiting_admin_id", {}).pop(chat_id)
    try:
        admin_id = int(text.strip())
    except ValueError:
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_admin_id_invalid"))
        app.bot_data["awaiting_admin_id"][chat_id] = action
        return

    if action == "remove" and admin_id == MASTER_ADMIN_ID:
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_admin_master_locked"))
        return
    cfg: Config = app.bot_data["cfg"]
    if action == "add":
        cfg.admin_chat_ids.add(admin_id)
        message_key = "msg_admin_id_added"
    else:
        cfg.admin_chat_ids.discard(admin_id)
        message_key = "msg_admin_id_removed"
    try:
        await asyncio.to_thread(
            update_admin_chat_ids,
            app.bot_data.get("config_path", "config.yaml"),
            cfg.admin_chat_ids,
        )
    except Exception as exc:
        await app.bot.send_message(chat_id, f"⚠️ {exc}")
        return
    await app.bot.send_message(chat_id, i18n.t(lang, message_key, chat_id=admin_id))
    await _goto(app, chat_id, "admin_ids")


async def _goto_teacher_list(app, chat_id) -> None:
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    lang = get_lang(app, chat_id)
    try:
        lessons = await asyncio.to_thread(tt.lessons_for, dt.datetime.now(cfg.tz).date())
    except EdupageError as e:
        await app.bot.send_message(chat_id, f"⚠️ {e}")
        return
    teachers = sorted({t.upper() for l in lessons for t in l["teachers"]})
    if not teachers:
        await app.bot.send_message(chat_id, "—")
        return
    from telegram import ReplyKeyboardMarkup
    rows = [teachers[i:i + 2] for i in range(0, len(teachers), 2)] + [[i18n.t(lang, "btn_back")]]
    app.bot_data.setdefault("nav", {})[chat_id] = "teacher_list"
    await app.bot.send_message(chat_id, i18n.t(lang, "title_teachers"),
                                reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def _start_teacher_search(app, chat_id) -> None:
    app.bot_data.setdefault("awaiting_teacher_search", set()).add(chat_id)
    lang = get_lang(app, chat_id)
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_teacher_name"))


# ============================================================
#  Штрафы — учёт нарушений (ZAMENA/TALABALARSONI/DARSBARBOD),
#  выборка за период и экспорт в Excel.
#
#  Активный мастер (ввод даты/периода/ФИО и т.д.) хранится в app.bot_data["pflow"]
#  по chat_id — единый счётчик шагов на весь раздел вместо кучи отдельных
#  awaiting_* флагов, потому что тут один связный сценарий, а не разные фичи.
# ============================================================

def _pflow(app) -> dict:
    return app.bot_data.setdefault("pflow", {})


def _parse_date(text: str, cfg: Config) -> dt.date | None:
    text = text.strip().lower()
    today = dt.datetime.now(cfg.tz).date()
    if text in ("сегодня", "today", "bugun"):
        return today
    if text in ("вчера", "yesterday", "kecha"):
        return today - dt.timedelta(days=1)
    if text in ("завтра", "tomorrow", "ertaga"):
        return today + dt.timedelta(days=1)
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


async def _lookup_lesson_for_violation(app, date: dt.date, period: int, teacher_query: str) -> dict | None:
    tt: EdupageTimetable = app.bot_data["tt"]
    try:
        lessons = await asyncio.to_thread(tt.lessons_at, date, period)
    except EdupageError:
        return None
    for l in lessons:
        if any(_teacher_matches(teacher_query, t) for t in l["teachers"]):
            return l
    return None


async def _send_violations_report(app, chat_id, records: list[dict]) -> None:
    lang = get_lang(app, chat_id)
    if not records:
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_no_violations"))
        return
    counts = Counter(r["type"] for r in records)
    summary = i18n.t(
        lang, "msg_violations_summary",
        total=len(records),
        zamena=counts.get("ZAMENA", 0),
        talaba=counts.get("TALABALARSONI", 0),
        darsbarbod=counts.get("DARSBARBOD", 0),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "shtrafy.xlsx"
        await asyncio.to_thread(penalties.export_excel, records, str(path))
        with path.open("rb") as f:
            await app.bot.send_document(chat_id, document=f, filename="shtrafy.xlsx", caption=summary)


async def _start_penalty_range(app, chat_id) -> None:
    _pflow(app)[chat_id] = {"kind": "range", "step": "start", "data": {}}
    lang = get_lang(app, chat_id)
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_start_date"))


async def _start_delete_violation(app, chat_id) -> None:
    """Начало процесса удаления нарушения - сначала выбираем период."""
    _pflow(app)[chat_id] = {"kind": "delete_range", "step": "start", "data": {}}
    lang = get_lang(app, chat_id)
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_start_date"))


async def _start_manage_posts(app, chat_id) -> None:
    """Начало процесса управления постами - выбор периода."""
    _pflow(app)[chat_id] = {"kind": "manage_posts_range", "step": "start", "data": {}}
    lang = get_lang(app, chat_id)
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_start_date"))


async def _show_manage_posts_menu(app, chat_id, start: dt.date, end: dt.date) -> None:
    """Показывает список постов за период с кнопками редактирования/удаления."""
    lang = get_lang(app, chat_id)
    records = penalties.filter_records(penalties.all_records(app), start, end)
    
    # Фильтруем только постые с message_id (отправленные в группу)
    posts = [r for r in records if r.get("message_id")]
    
    if not posts:
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_no_posts_found"))
        return
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    for rec in posts:
        d = dt.date.fromisoformat(rec["date"])
        groups = " / ".join(rec.get("groups", [])) or "?"
        teacher = rec.get("teacher", "?")
        subject = rec.get("subject", "?")
        text = (f"#{rec['type']} • {d.strftime('%d.%m.%y')} • пара {rec['period']} • {teacher}\n"
                f"{subject} [{groups}]")
        
        if rec.get("students") is not None:
            text += f"\n👥 {rec['students']} студентов"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(i18n.t(lang, "btn_edit_post"), callback_data=f"editpost:{rec['id']}"),
            InlineKeyboardButton(i18n.t(lang, "btn_delete_post"), callback_data=f"deletepost:{rec['id']}"),
        ]])
        await app.bot.send_message(chat_id, text, reply_markup=kb)


async def _show_delete_violations_menu(app, chat_id, start: dt.date, end: dt.date) -> None:
    """Показывает список нарушений за период с кнопками для удаления."""
    lang = get_lang(app, chat_id)
    records = penalties.filter_records(penalties.all_records(app), start, end)
    
    if not records:
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_no_violations_to_delete"))
        return
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    # Группируем штрафы по дате и паре для удобства
    for rec in records:
        d = dt.date.fromisoformat(rec["date"])
        groups = " / ".join(rec.get("groups", [])) or "?"
        teacher = rec.get("teacher", "?")
        subject = rec.get("subject", "?")
        text = f"#{rec['type']} • {d.strftime('%d.%m.%y')} • пара {rec['period']} • {teacher}\n{subject} [{groups}]"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delviol:{rec['id']}")
        ]])
        await app.bot.send_message(chat_id, text, reply_markup=kb)


@admin_only
async def on_delete_violation(update, context):
    """Обработчик удаления конкретного нарушения."""
    app = context.application
    q = update.callback_query
    _, record_id = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    if penalties.delete(app, record_id):
        await q.message.reply_text(i18n.t(lang, "msg_violation_deleted"))
    else:
        await q.message.reply_text(i18n.t(lang, "msg_violation_delete_failed"))


@admin_only
async def on_edit_post(update, context):
    """Обработчик редактирования поста в группе."""
    app = context.application
    q = update.callback_query
    _, record_id = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    # Сохраняем record_id для редактирования
    _pflow(app)[chat_id] = {"kind": "edit_post", "record_id": record_id, "step": "choose_field"}
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Изменить кол-во студентов", callback_data=f"editfield:{record_id}:students")],
        [InlineKeyboardButton("📝 Изменить текст целиком", callback_data=f"editfield:{record_id}:caption")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"editcancel:{record_id}")],
    ])
    await q.message.reply_text("Что редактировать?", reply_markup=kb)


@admin_only
async def on_delete_post(update, context):
    """Обработчик удаления поста из группы и штрафов."""
    app = context.application
    cfg: Config = app.bot_data["cfg"]
    q = update.callback_query
    _, record_id = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    # Получаем информацию о посте
    records = penalties.all_records(app)
    rec = next((r for r in records if r["id"] == record_id), None)
    
    if not rec:
        await q.message.reply_text(i18n.t(lang, "msg_violation_delete_failed"))
        return
    
    # Удаляем пост из группы
    if rec.get("message_id") and rec.get("message_chat_id"):
        try:
            await app.bot.delete_message(
                chat_id=rec["message_chat_id"],
                message_id=rec["message_id"]
            )
        except Exception as e:
            log.warning("Не удалось удалить пост из группы: %s", e)
    
    # Удаляем из штрафов
    if penalties.delete(app, record_id):
        await q.message.reply_text(i18n.t(lang, "msg_post_deleted"))
    else:
        await q.message.reply_text(i18n.t(lang, "msg_violation_delete_failed"))


@admin_only
async def on_edit_post_field(update, context):
    """Обработчик выбора поля для редактирования."""
    app = context.application
    q = update.callback_query
    _, record_id, field = (q.data or "").split(":", 2)
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    # Сохраняем поле для редактирования
    _pflow(app)[chat_id] = {
        "kind": "edit_post_value",
        "record_id": record_id,
        "field": field,
    }
    
    if field == "students":
        await q.message.reply_text("Введите новое кол-во студентов (число):")
    elif field == "caption":
        await q.message.reply_text("Введите новый текст для поста:")


@admin_only
async def on_edit_post_cancel(update, context):
    """Отмена редактирования."""
    app = context.application
    q = update.callback_query
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    _pflow(app).pop(chat_id, None)
    await q.message.reply_text("Редактирование отменено.")


async def _show_penalty_filter_menu(app, chat_id, start: dt.date, end: dt.date) -> None:
    lang = get_lang(app, chat_id)
    _pflow(app)[chat_id] = {"kind": "filter", "step": "choose", "data": {"start": start, "end": end}}
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(i18n.t(lang, "btn_penalty_all"), callback_data="pflt:all")],
        [InlineKeyboardButton(i18n.t(lang, "btn_penalty_by_teacher"), callback_data="pflt:teacher")],
        [InlineKeyboardButton(i18n.t(lang, "btn_penalty_by_type"), callback_data="pflt:type")],
    ])
    await app.bot.send_message(
        chat_id,
        i18n.t(lang, "msg_penalty_range_chosen",
               start=start.strftime("%d.%m.%Y"), end=end.strftime("%d.%m.%Y")),
        reply_markup=kb,
    )


async def _start_add_violation(app, chat_id) -> None:
    lang = get_lang(app, chat_id)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"#{t}", callback_data=f"addviol:{t}")]
                                for t in penalties.TYPES])
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_choose_violation_type"), reply_markup=kb)


@admin_only
async def on_add_violation_type(update, context):
    app = context.application
    q = update.callback_query
    _, vtype = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    _pflow(app)[chat_id] = {"kind": "add", "step": "date", "data": {"type": vtype}}
    lang = get_lang(app, chat_id)
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    # Показываем кнопки быстрого выбора даты
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    cfg: Config = app.bot_data["cfg"]
    today = dt.datetime.now(cfg.tz).date()
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(i18n.t(lang, "btn_yesterday"), callback_data=f"qdate:{(today - dt.timedelta(days=1)).isoformat()}"),
            InlineKeyboardButton(i18n.t(lang, "btn_today"), callback_data=f"qdate:{today.isoformat()}"),
            InlineKeyboardButton(i18n.t(lang, "btn_tomorrow"), callback_data=f"qdate:{(today + dt.timedelta(days=1)).isoformat()}"),
        ]
    ])
    await q.message.reply_text(i18n.t(lang, "msg_enter_violation_date"), reply_markup=kb)


@admin_only
async def on_quick_date_select(update, context):
    """Обработчик быстрого выбора даты для добавления нарушения."""
    app = context.application
    q = update.callback_query
    _, date_str = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    flow = _pflow(app)
    state = flow.get(chat_id)
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    if state is None or state.get("kind") != "add" or state.get("step") != "date":
        return
    
    state["data"]["date"] = date_str
    state["step"] = "period"
    await q.message.reply_text(i18n.t(lang, "msg_enter_violation_period"))


@admin_only
async def on_duplicate_confirm(update, context):
    """Обработчик подтверждения добавления дубликата нарушения."""
    app = context.application
    q = update.callback_query
    _, answer = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    flow = _pflow(app)
    state = flow.get(chat_id)
    lang = get_lang(app, chat_id)
    
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    if state is None or state.get("kind") != "add" or state.get("step") != "confirm_duplicate":
        return
    
    if answer == "yes":
        # Добавляем нарушение несмотря на дубликат
        data = state["data"]
        flow.pop(chat_id, None)
        rec = penalties.add(
            app,
            date=dt.date.fromisoformat(data["date"]),
            period=data["period"],
            teacher=data["teacher"],
            subject=data["subject"],
            groups=data["groups"],
            vtype=data["type"],
            link=data.get("link"),
        )
        await q.message.reply_text(
            i18n.t(lang, "msg_violation_saved",
                   type=f"#{rec['type']}", date=rec["date"], period=rec["period"],
                   teacher=rec["teacher"]),
        )
    else:
        # Отменяем добавление
        flow.pop(chat_id, None)
        await q.message.reply_text(i18n.t(lang, "msg_cancelled"))


@admin_only
async def on_penalty_filter(update, context):
    app = context.application
    q = update.callback_query
    _, kind = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    lang = get_lang(app, chat_id)
    flow = _pflow(app)
    state = flow.get(chat_id)
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    if state is None or state.get("kind") != "filter":
        return
    start, end = state["data"]["start"], state["data"]["end"]

    if kind == "all":
        flow.pop(chat_id, None)
        records = penalties.filter_records(penalties.all_records(app), start, end)
        await _send_violations_report(app, chat_id, records)
        return

    if kind == "teacher":
        state["kind"] = "filter_teacher"
        await q.message.reply_text(i18n.t(lang, "msg_enter_filter_teacher"))
        return

    if kind == "type":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"#{t}", callback_data=f"pflttype:{t}")]
                                    for t in penalties.TYPES])
        await q.message.reply_text(i18n.t(lang, "msg_choose_violation_type"), reply_markup=kb)
        return


@admin_only
async def on_penalty_filter_type(update, context):
    app = context.application
    q = update.callback_query
    _, vtype = (q.data or "").split(":", 1)
    chat_id = q.message.chat_id
    flow = _pflow(app)
    state = flow.pop(chat_id, None)
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    if state is None or state.get("kind") != "filter":
        return
    start, end = state["data"]["start"], state["data"]["end"]
    records = penalties.filter_records(penalties.all_records(app), start, end, vtype=vtype)
    await _send_violations_report(app, chat_id, records)


async def _handle_pflow_text(app, chat_id, text: str) -> bool:
    """Обрабатывает текстовый шаг активного мастера раздела «Штрафы»
    (диапазон дат / фильтр по преподавателю / ручное добавление нарушения).
    Возвращает True, если текст был обработан (вызывающий должен остановиться)."""
    cfg: Config = app.bot_data["cfg"]
    lang = get_lang(app, chat_id)
    flow = _pflow(app)
    state = flow.get(chat_id)
    if state is None:
        return False

    if text in (i18n.t(lang, "btn_back"), i18n.t(lang, "btn_cancel")):
        flow.pop(chat_id, None)
        return False  # пусть сработает обычная навигация "Назад"

    kind = state["kind"]
    data = state["data"]

    if kind == "filter_teacher":
        flow.pop(chat_id, None)
        records = penalties.filter_records(
            penalties.all_records(app), data["start"], data["end"], teacher_query=text
        )
        await _send_violations_report(app, chat_id, records)
        return True

    if kind == "range":
        d = _parse_date(text, cfg)
        if d is None:
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_date_invalid"))
            return True
        if state["step"] == "start":
            data["start"] = d
            state["step"] = "end"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_end_date"))
            return True
        # step == "end"
        flow.pop(chat_id, None)
        start, end = data["start"], d
        if end < start:
            start, end = end, start
        await _show_penalty_filter_menu(app, chat_id, start, end)
        return True

    if kind == "add":
        step = state["step"]
        if step == "date":
            d = _parse_date(text, cfg)
            if d is None:
                await app.bot.send_message(chat_id, i18n.t(lang, "msg_date_invalid"))
                return True
            data["date"] = d.isoformat()
            state["step"] = "period"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_period"))
            return True
        if step == "period":
            if not text.isdigit() or not (1 <= int(text) <= 8):
                await app.bot.send_message(chat_id, i18n.t(lang, "msg_period_invalid"))
                return True
            data["period"] = int(text)
            state["step"] = "teacher"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_teacher"))
            return True
        if step == "teacher":
            data["teacher"] = text.strip().upper()
            found = await _lookup_lesson_for_violation(
                app, dt.date.fromisoformat(data["date"]), data["period"], data["teacher"]
            )
            if found:
                data["subject"] = found["subject"]
                data["groups"] = found["classes"]
                state["step"] = "link"
                await app.bot.send_message(
                    chat_id,
                    i18n.t(lang, "msg_violation_lesson_found",
                           subject=found["subject"], groups=" / ".join(found["classes"])),
                )
                await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_link"))
            else:
                state["step"] = "subject"
                await app.bot.send_message(chat_id, i18n.t(lang, "msg_violation_lesson_not_found"))
                await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_subject"))
            return True
        if step == "subject":
            data["subject"] = text.strip()
            state["step"] = "groups"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_groups"))
            return True
        if step == "groups":
            data["groups"] = [g.strip() for g in re.split(r"[/,]", text) if g.strip()]
            state["step"] = "link"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_violation_link"))
            return True
        if step == "link":
            link = None if text.strip() in ("-", "") else text.strip()
            
            # Проверяем дублирование
            records = penalties.all_records(app)
            duplicate = penalties.find_duplicate(
                records,
                dt.date.fromisoformat(data["date"]),
                data["period"],
                data["teacher"],
                data["groups"]
            )
            
            if duplicate:
                # Есть дубликат - спрашиваем подтверждение
                state["step"] = "confirm_duplicate"
                state["data"]["link"] = link
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Добавить", callback_data="dupconfirm:yes"),
                        InlineKeyboardButton("❌ Отмена", callback_data="dupconfirm:no"),
                    ]
                ])
                await app.bot.send_message(
                    chat_id,
                    i18n.t(lang, "msg_duplicate_violation",
                           type=f"#{duplicate['type']}", 
                           date=duplicate["date"], 
                           period=duplicate["period"],
                           teacher=duplicate["teacher"]),
                    reply_markup=kb,
                )
            else:
                # Нет дубликата - добавляем напрямую
                flow.pop(chat_id, None)
                rec = penalties.add(
                    app,
                    date=dt.date.fromisoformat(data["date"]),
                    period=data["period"],
                    teacher=data["teacher"],
                    subject=data["subject"],
                    groups=data["groups"],
                    vtype=data["type"],
                    link=link,
                )
                await app.bot.send_message(
                    chat_id,
                    i18n.t(lang, "msg_violation_saved",
                           type=f"#{rec['type']}", date=rec["date"], period=rec["period"],
                           teacher=rec["teacher"]),
                )
            return True

    if kind == "delete_range":
        d = _parse_date(text, cfg)
        if d is None:
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_date_invalid"))
            return True
        if state["step"] == "start":
            data["start"] = d
            state["step"] = "end"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_end_date"))
            return True
        # step == "end"
        flow.pop(chat_id, None)
        start, end = data["start"], d
        if end < start:
            start, end = end, start
        await _show_delete_violations_menu(app, chat_id, start, end)
        return True

    if kind == "manage_posts_range":
        d = _parse_date(text, cfg)
        if d is None:
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_date_invalid"))
            return True
        if state["step"] == "start":
            data["start"] = d
            state["step"] = "end"
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_enter_end_date"))
            return True
        # step == "end"
        flow.pop(chat_id, None)
        start, end = data["start"], d
        if end < start:
            start, end = end, start
        await _show_manage_posts_menu(app, chat_id, start, end)
        return True

    if kind == "edit_post_value":
        record_id = state.get("record_id")
        field = state.get("field")
        flow.pop(chat_id, None)
        
        records = penalties.all_records(app)
        rec = next((r for r in records if r["id"] == record_id), None)
        
        if not rec:
            await app.bot.send_message(chat_id, i18n.t(lang, "msg_violation_delete_failed"))
            return True
        
        if field == "students":
            try:
                new_count = int(text.strip())
                if new_count < 0:
                    await app.bot.send_message(chat_id, "Кол-во студентов не может быть отрицательным.")
                    return True
                
                # Обновляем пост в группе
                if rec.get("message_id") and rec.get("message_chat_id"):
                    old_caption = (
                        f"#{rec['type']} • {dt.date.fromisoformat(rec['date']).strftime('%d.%m.%y')} • "
                        f"пара {rec['period']} • {rec.get('teacher', '?')}\n"
                        f"{rec.get('subject', '?')} [{' / '.join(rec.get('groups', []))}]\n"
                        f"👥 {new_count} студентов"
                    )
                    try:
                        await app.bot.edit_message_caption(
                            chat_id=rec["message_chat_id"],
                            message_id=rec["message_id"],
                            caption=old_caption
                        )
                    except Exception as e:
                        log.warning("Не удалось отредактировать пост: %s", e)
                        await app.bot.send_message(chat_id, f"Ошибка при редактировании: {e}")
                        return True
                
                # Обновляем в штрафах
                penalties.update(app, record_id, students=new_count)
                await app.bot.send_message(chat_id, f"✅ Кол-во студентов изменено на {new_count}")
            except ValueError:
                await app.bot.send_message(chat_id, "Пожалуйста, введите число.")
                return True
        
        elif field == "caption":
            # Обновляем пост в группе
            if rec.get("message_id") and rec.get("message_chat_id"):
                try:
                    await app.bot.edit_message_caption(
                        chat_id=rec["message_chat_id"],
                        message_id=rec["message_id"],
                        caption=text
                    )
                except Exception as e:
                    log.warning("Не удалось отредактировать пост: %s", e)
                    await app.bot.send_message(chat_id, f"Ошибка при редактировании: {e}")
                    return True
            
            await app.bot.send_message(chat_id, "✅ Текст поста изменен")
        
        return True

    return False


async def send_health_check(app, chat_id) -> None:
    cfg: Config = app.bot_data["cfg"]
    lang = get_lang(app, chat_id)
    started = app.bot_data.get("started_at")
    lines = [i18n.t(lang, "msg_bot_status_ok")]
    if started:
        total_sec = int((dt.datetime.now(cfg.tz) - started).total_seconds())
        h, rem = divmod(total_sec, 3600)
        lines.append(i18n.t(lang, "msg_bot_uptime", h=h, m=rem // 60))
    lines.append(i18n.t(lang, "msg_bot_mode", mode=cfg.mode))
    lines.append(i18n.t(lang, "msg_bot_cameras_count", n=len(cfg.cameras)))
    await app.bot.send_message(chat_id, "\n".join(lines))


async def send_camera_settings_room(app, chat_id, room: str) -> None:
    cfg: Config = app.bot_data["cfg"]
    lang = get_lang(app, chat_id)
    cam = cfg.camera_for_room(room)
    if not cam:
        await app.bot.send_message(
            chat_id, i18n.t(lang, "msg_room_not_configured", room=room, rooms="")
        )
        return
    url = str(cam.get("url") or "")
    m = re.search(r"://([^/]+)", url)
    ip = m.group(1) if m else "?"
    password = str(cam.get("password") or "")
    masked = ("•" * max(len(password) - 2, 0)) + password[-2:] if password else "—"
    text = f"📷 {norm_room(room)}\nIP: {ip}\n{i18n.t(lang, 'label_password')}: {masked}"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(i18n.t(lang, "btn_edit_ip"), callback_data=f"camip:{room}"),
        InlineKeyboardButton(i18n.t(lang, "btn_edit_password"), callback_data=f"campass:{room}"),
    ]])
    await app.bot.send_message(chat_id, text, reply_markup=kb)


@admin_only
async def on_camera_edit_button(update, context):
    app = context.application
    q = update.callback_query
    action, room = (q.data or "").split(":", 1)
    field = "url" if action == "camip" else "password"
    chat_id = q.message.chat_id
    app.bot_data.setdefault("awaiting_camera_edit", {})[chat_id] = (room, field)
    lang = get_lang(app, chat_id)
    await q.answer()
    await q.message.reply_text(
        i18n.t(lang, "msg_enter_new_ip" if field == "url" else "msg_enter_new_password")
    )


async def apply_camera_edit(app, chat_id, room: str, field: str, value: str) -> None:
    cfg: Config = app.bot_data["cfg"]
    lang = get_lang(app, chat_id)
    value = value.strip()
    if field == "url" and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value):
        await app.bot.send_message(chat_id, i18n.t(lang, "msg_ip_invalid"))
        app.bot_data.setdefault("awaiting_camera_edit", {})[chat_id] = (room, field)
        return
    config_path = app.bot_data.get("config_path", "config.yaml")
    try:
        await asyncio.to_thread(update_camera_config, config_path, room, field, value)
    except Exception as e:
        await app.bot.send_message(chat_id, f"⚠️ {e}")
        return
    cam = cfg.camera_for_room(room)
    if cam is not None:
        if field == "url":
            old = str(cam.get("url") or "")
            cam["url"] = (re.sub(r"://[^/]+", f"://{value}", old, count=1) if old
                          else f"http://{value}/ISAPI/Streaming/channels/101/picture")
        else:
            cam["password"] = value
    await app.bot.send_message(chat_id, i18n.t(lang, "msg_camera_updated"))


ACTION_HANDLERS = {
    "week_schedule": send_week_plan,
    "day_schedule": send_plan,
    "check_cams": send_camera_health,
    "teacher_search": _start_teacher_search,
    "teacher_list": _goto_teacher_list,
    "health_check": send_health_check,
    "penalty_period": _start_penalty_range,
    "penalty_add": _start_add_violation,
    "penalty_delete": _start_delete_violation,
    "manage_posts": _start_manage_posts,
}


async def cmd_menu(update, context):
    await _goto(context.application, update.effective_chat.id, "main")


@admin_only
async def on_text(update, context):
    app = context.application
    cfg: Config = app.bot_data["cfg"]
    chat_id = update.effective_chat.id
    text = (update.effective_message.text or "").strip()
    lang = get_lang(app, chat_id)
    nav = app.bot_data.setdefault("nav", {})
    cur = nav.get(chat_id, "main")

    # --- свободный ввод, который бот ждёт после нажатия отдельной кнопки ---
    if chat_id in app.bot_data.setdefault("awaiting_teacher_search", set()):
        app.bot_data["awaiting_teacher_search"].discard(chat_id)
        await send_teacher_photo(app, chat_id, text)
        return

    cam_edit = app.bot_data.setdefault("awaiting_camera_edit", {})
    if chat_id in cam_edit:
        room, field = cam_edit.pop(chat_id)
        await apply_camera_edit(app, chat_id, room, field, text)
        return

    cap_edit = app.bot_data.setdefault("awaiting_caption_edit", {})
    if chat_id in cap_edit:
        pid = cap_edit.pop(chat_id)
        await apply_caption_edit(app, chat_id, pid, text)
        return

    if _is_master_admin(chat_id) and chat_id in app.bot_data.setdefault("awaiting_admin_id", {}):
        await _apply_admin_id_change(app, chat_id, text)
        return

    if await _handle_pflow_text(app, chat_id, text):
        return

    # --- выбор языка (названия языков не переводятся) ---
    if text in _LANG_CODE_BY_NAME:
        new_lang = _LANG_CODE_BY_NAME[text]
        set_lang(app, chat_id, new_lang)
        await update.effective_message.reply_text(i18n.t(new_lang, "msg_lang_changed", lang=text))
        await _goto(app, chat_id, "main")
        return

    if text == i18n.t(lang, "btn_back"):
        await _goto(app, chat_id, STATE_PARENT.get(cur, "main"))
        return

    if text == i18n.t(lang, "btn_all") and cur in ROOMS_BY_STATE:
        rooms = ROOMS_BY_STATE.get(cur, [])
        await update.effective_message.reply_text(i18n.t(lang, "msg_all_sending", floor=text))
        for room in rooms:
            await send_room_photo(app, chat_id, room)
        return

    if cur == "report":
        for n in range(1, 9):
            if text == i18n.t(lang, "btn_period", n=n):
                await update.effective_message.reply_text(i18n.t(lang, "msg_checking_period", period=n))
                await run_check(app, n, announce_chat=chat_id)
                return

    id_ = _resolve_menu_id(cur, lang, text, chat_id)

    if id_ in STATE_ITEMS or id_ in ROOMS_BY_STATE or id_ in ("lang", "report"):
        await _goto(app, chat_id, id_)
        return

    handler = ACTION_HANDLERS.get(id_)
    if handler is not None:
        await handler(app, chat_id)
        return

    if cur == "admin_ids" and _is_master_admin(chat_id):
        if id_ == "admin_add":
            await _start_admin_id_change(app, chat_id, "add")
            return
        if id_ == "admin_remove":
            await _start_admin_id_change(app, chat_id, "remove")
            return

    if norm_room(text) in cfg.cameras:
        if cur == "camera_settings":
            await send_camera_settings_room(app, chat_id, text)
        else:
            await send_room_photo(app, chat_id, text)
        return

    if cur == "teacher_list":
        await send_teacher_photo(app, chat_id, text)
        return

    await update.effective_message.reply_text(
        i18n.t(lang, "msg_unrecognized"), reply_markup=_reply_markup(cur, lang, chat_id)
    )


@admin_only
async def cmd_plan(update, context):
    await send_plan(context.application, update.effective_chat.id)


@admin_only
async def cmd_check(update, context):
    app = context.application
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.effective_message.reply_text("Использование: /check <номер пары>, например /check 2")
        return
    period = int(args[0])
    await update.effective_message.reply_text(f"Запускаю проверку пары {period}...")
    await run_check(app, period, announce_chat=update.effective_chat.id)


@admin_only
async def cmd_rooms(update, context):
    await send_camera_health(context.application, update.effective_chat.id)


@admin_only
async def cmd_room(update, context):
    room = " ".join(context.args or []).strip()
    if not room:
        await update.effective_message.reply_text(
            'Использование: /room <аудитория>, например /room LAB 406'
        )
        return
    await send_room_photo(context.application, update.effective_chat.id, room)


@admin_only
async def cmd_teacher(update, context):
    query = " ".join(context.args or []).strip()
    if not query:
        await update.effective_message.reply_text(
            "Использование: /teacher <фамилия>, например /teacher KHAMIDULLA"
        )
        return
    await send_teacher_photo(context.application, update.effective_chat.id, query)


async def job_check(context):
    period = context.job.data["period"]
    cfg: Config = context.application.bot_data["cfg"]
    today = dt.datetime.now(cfg.tz)
    if today.weekday() not in cfg.working_days:
        return
    await run_check(context.application, period)


async def run_presence_check(app, period: int) -> None:
    """Лёгкая проверка «есть ли вообще кто-то в аудитории» — без счёта/кнопок/группы.
    Ловит пустую аудиторию (отменённая пара / никто не пришёл), но НЕ отличает
    "нет преподавателя, есть студенты" — это разумно, если студенты уже видны на фото."""
    cfg: Config = app.bot_data["cfg"]
    tt: EdupageTimetable = app.bot_data["tt"]
    if not cfg.counting_enabled or not cfg.review_chat_id:
        return
    # Преобразуем review_chat_id если это список
    review_chat = cfg.review_chat_id[0] if isinstance(cfg.review_chat_id, list) else cfg.review_chat_id
    date = dt.datetime.now(cfg.tz).date()
    if date.weekday() not in cfg.working_days:
        return
    try:
        lessons = await asyncio.to_thread(tt.lessons_at, date, period)
    except EdupageError:
        return

    from . import people_counter
    for lesson in lessons:
        cam = cfg.camera_for_room(lesson["room"])
        if not cam:
            continue
        try:
            photo = await asyncio.to_thread(grab_snapshot, cam)
            counting = camera_counting_settings(cfg, cam)
            detected, _ = await asyncio.to_thread(
                people_counter.count_people,
                photo,
                counting["model_name"],
                counting["confidence"],
                imgsz=counting["imgsz"],
                iou=counting["iou"],
                augment=counting["augment"],
            )
        except Exception:
            log.exception("Проверка присутствия: ошибка камеры %s", lesson["room"])
            continue
        if detected == 0:
            await app.bot.send_message(
                review_chat,
                f"⚠️ Пара {period}, {lesson['room']} ({lesson['subject']}): "
                f"через {cfg.presence_check_minutes} мин после начала на камере никого не видно. "
                "Возможно, преподаватель опаздывает или пара не состоится.",
            )


async def job_presence_check(context):
    period = context.job.data["period"]
    cfg: Config = context.application.bot_data["cfg"]
    today = dt.datetime.now(cfg.tz)
    if today.weekday() not in cfg.working_days:
        return
    await run_presence_check(context.application, period)


async def job_cleanup_pending(context):
    """Убирает из памяти фото режима review, которые давно остались без ответа."""
    cfg: Config = context.application.bot_data["cfg"]
    pending: dict = context.application.bot_data.setdefault("pending", {})
    cutoff = dt.datetime.now(cfg.tz) - dt.timedelta(hours=PENDING_MAX_AGE_HOURS)
    stale = [pid for pid, item in pending.items() if item.get("created", cutoff) < cutoff]
    for pid in stale:
        pending.pop(pid, None)
    if stale:
        log.info("Очистка pending: удалено %s старых записей (>%sч без ответа)",
                  len(stale), PENDING_MAX_AGE_HOURS)


async def job_day_plan(context):
    cfg: Config = context.application.bot_data["cfg"]
    now = dt.datetime.now(cfg.tz)
    if now.weekday() not in cfg.working_days or not cfg.review_chat_id:
        return
    # Преобразуем review_chat_id если это список
    review_chat = cfg.review_chat_id[0] if isinstance(cfg.review_chat_id, list) else cfg.review_chat_id
    tt: EdupageTimetable = context.application.bot_data["tt"]
    try:
        lessons = await asyncio.to_thread(tt.lessons_for, now.date())
    except EdupageError as e:
        await context.bot.send_message(review_chat, f"⚠️ Не удалось получить расписание: {e}")
        return
    with_cam = sum(1 for l in lessons if cfg.camera_for_room(l["room"]))
    await context.bot.send_message(
        review_chat,
        f"📅 Сегодня {now.date()}: занятий {len(lessons)}, "
        f"будет проверено по камерам: {with_cam}.\nПодробности: /plan",
    )


# ============================================================
#  Запуск бота
# ============================================================

BOT_COMMANDS = [
    ("menu", "кнопочное меню"),
    ("id", "ID этого чата")
]


async def _post_init(app) -> None:
    from telegram import BotCommand
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in BOT_COMMANDS])
    for code in (None, "ru", "en", "uz"):
        lang = code or i18n.DEFAULT_LANG
        try:
            await app.bot.set_my_short_description(i18n.t(lang, "bot_short_description"), language_code=code)
            await app.bot.set_my_description(i18n.t(lang, "bot_description"), language_code=code)
        except Exception:
            log.exception("Не удалось установить описание бота (language_code=%s)", code)


def run_bot(cfg: Config, config_path: str = "config.yaml") -> None:
    try:
        from telegram.ext import (
            Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
        )
    except ImportError:
        print("Установите зависимости:  pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(1)

    if not cfg.bot_token or "ВСТАВЬТЕ" in cfg.bot_token:
        print("Заполните telegram.bot_token в config.yaml", file=sys.stderr)
        raise SystemExit(1)

    app = Application.builder().token(cfg.bot_token).post_init(_post_init).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["tt"] = EdupageTimetable(cfg.school)
    app.bot_data["config_path"] = config_path
    app.bot_data["started_at"] = dt.datetime.now(cfg.tz)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(
        on_callback, pattern=r"^(dec|inc|noop|skip|send|edit|reset|roompick|roomcancel):"
    ))
    app.add_handler(CallbackQueryHandler(on_room_pick_select, pattern=r"^roomsel:"))
    app.add_handler(CallbackQueryHandler(on_check_room_button, pattern=r"^checkroom:"))
    app.add_handler(CallbackQueryHandler(on_camera_edit_button, pattern=r"^cam(ip|pass):"))
    app.add_handler(CallbackQueryHandler(on_add_violation_type, pattern=r"^addviol:"))
    app.add_handler(CallbackQueryHandler(on_quick_date_select, pattern=r"^qdate:"))
    app.add_handler(CallbackQueryHandler(on_duplicate_confirm, pattern=r"^dupconfirm:"))
    app.add_handler(CallbackQueryHandler(on_delete_violation, pattern=r"^delviol:"))
    app.add_handler(CallbackQueryHandler(on_edit_post, pattern=r"^editpost:"))
    app.add_handler(CallbackQueryHandler(on_delete_post, pattern=r"^deletepost:"))
    app.add_handler(CallbackQueryHandler(on_edit_post_field, pattern=r"^editfield:"))
    app.add_handler(CallbackQueryHandler(on_edit_post_cancel, pattern=r"^editcancel:"))
    app.add_handler(CallbackQueryHandler(on_penalty_filter, pattern=r"^pflt:"))
    app.add_handler(CallbackQueryHandler(on_penalty_filter_type, pattern=r"^pflttype:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    jq = app.job_queue
    if jq is None:
        print('Установите планировщик:  pip install "python-telegram-bot[job-queue]"',
              file=sys.stderr)
        raise SystemExit(1)

    for period in sorted(cfg.periods):
        t = cfg.check_time(period)
        aware_time = cfg.tz.localize(dt.datetime.combine(dt.date.today(), t)).timetz()
        jq.run_daily(
            job_check,
            time=aware_time,
            data={"period": period},
            name=f"check_p{period}",
        )
        log.info("Запланирована проверка пары %s в %s", period, t.strftime("%H:%M"))

        if cfg.presence_check_minutes is not None:
            pt = cfg.presence_check_time(period)
            aware_pt = cfg.tz.localize(dt.datetime.combine(dt.date.today(), pt)).timetz()
            jq.run_daily(
                job_presence_check,
                time=aware_pt,
                data={"period": period},
                name=f"presence_p{period}",
            )

    if cfg.day_plan_time:
        jq.run_daily(
            job_day_plan,
            time=cfg.tz.localize(
                dt.datetime.combine(dt.date.today(), cfg.day_plan_time)).timetz(),
            name="day_plan",
        )

    jq.run_repeating(job_cleanup_pending, interval=dt.timedelta(hours=24),
                      first=dt.timedelta(minutes=5), name="cleanup_pending")

    log.info("Бот запущен. Режим: %s. Ctrl+C для остановки.", cfg.mode)
    app.run_polling(allowed_updates=["message", "callback_query"])


# ============================================================
#  CLI-утилиты для отладки (без Telegram)
# ============================================================

def cli_print_timetable(cfg: Config, date_str: str | None) -> None:
    date = dt.date.fromisoformat(date_str) if date_str else dt.datetime.now(cfg.tz).date()
    tt = EdupageTimetable(cfg.school)
    lessons = tt.lessons_for(date)
    print(f"Расписание на {date} ({['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][date.weekday()]}):\n")
    if not lessons:
        print("  занятий нет")
        return
    cur = None
    for l in lessons:
        if l["period"] != cur:
            cur = l["period"]
            start = cfg.periods.get(cur)
            print(f"--- Пара {cur}" + (f" ({start.strftime('%H:%M')})" if start else ""))
        cam = "камера ✅" if cfg.camera_for_room(l["room"]) else "камеры нет 🚫"
        print(f"  [{l['room']:>12}] {l['subject']} | "
              f"{', '.join(t.upper() for t in l['teachers'])} | "
              f"{' / '.join(l['classes'])} | {cam}")


def cli_test_camera(cfg: Config, room: str) -> None:
    cam = cfg.camera_for_room(room)
    if not cam:
        print(f"Камера для аудитории {room!r} не найдена в config.yaml")
        print("Настроены:", ", ".join(sorted(cfg.cameras)) or "(нет)")
        raise SystemExit(1)
    source = "webcam index " + str(cam.get("index", 0)) if cam.get("type") == "webcam" else cam.get("url")
    print(f"Получаю снимок с {source} ...")
    photo = grab_snapshot(cam)
    fname = f"snapshot_{norm_room(room).replace(' ', '_')}.jpg"
    with open(fname, "wb") as f:
        f.write(photo)
    print(f"Снимок сохранён: {fname} ({len(photo)} байт)")
    if cfg.counting_enabled:
        from . import people_counter
        counting = camera_counting_settings(cfg, cam)
        count, annotated = people_counter.count_people(
            photo,
            counting["model_name"],
            counting["confidence"],
            imgsz=counting["imgsz"],
            iou=counting["iou"],
            augment=counting["augment"],
        )
        aname = fname.replace(".jpg", "_detected.jpg")
        with open(aname, "wb") as f:
            f.write(annotated)
        print(f"Найдено людей: {count}. Файл с рамками: {aname}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TTPU Monitor")
    parser.add_argument("-c", "--config", default="config.yaml", help="путь к config.yaml")
    parser.add_argument("--print-timetable", nargs="?", const="", metavar="ГГГГ-ММ-ДД",
                        help="показать расписание и выйти")
    parser.add_argument("--test-camera", metavar="АУДИТОРИЯ",
                        help='проверить камеру, например --test-camera "LAB 406"')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = Config(args.config)

    if args.print_timetable is not None:
        cli_print_timetable(cfg, args.print_timetable or None)
        return
    if args.test_camera:
        cli_test_camera(cfg, args.test_camera)
        return
    run_bot(cfg, args.config)


if __name__ == "__main__":
    main()
