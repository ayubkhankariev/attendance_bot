"""Переводы интерфейса бота (кнопки, заголовки меню, короткие сообщения).

Область перевода — статичный "каркас" интерфейса (кнопки, заголовки, типовые
уведомления). Данные из расписания (предметы, ФИО преподавателей, названия
групп) приходят с EduPage как есть и не переводятся — это исходные данные,
а не текст интерфейса.

Использование: t(lang, "btn_schedule") -> локализованная строка.
Если ключа нет для языка (или сам язык неизвестен) — берётся русский вариант,
если нет и там — возвращается сам ключ (чтобы не падать).
"""
from __future__ import annotations

DEFAULT_LANG = "ru"
LANGUAGES = {"ru": "Русский", "en": "English", "uz": "O'zbekcha"}

TEXT: dict[str, dict[str, str]] = {
    "ru": {
        "btn_schedule": "📅 Расписание",
        "btn_cameras": "🎥 Камеры-Аудитории",
        "btn_teachers": "🧑‍🏫 Преподаватели",
        "btn_penalties": "⚠️ Штрафы",
        "btn_settings": "⚙️ Настройки",

        "btn_week_schedule": "🗓 Расписание недели",
        "btn_day_schedule": "📆 Расписание дня",
        "btn_report": "📊 Отчёт",

        "btn_building_a": "🏢 A здание",
        "btn_building_b": "🏢 B здание",
        "btn_building_c": "🏢 C здание",
        "btn_building_mech": "🏢 Mechatronics",
        "btn_check_cams": "📡 Проверка камер",
        
        "btn_floor_4": "4 этаж",
        "btn_floor_3": "3 этаж",
        "btn_floor_2": "2 этаж",
        "btn_floor_1": "1 этаж",
        "btn_all": "📸 ВСЕ",

        "btn_teacher_search": "🔍 Поиск",
        "btn_teacher_list": "📋 Список преподавателей",

        "btn_lang": "🌐 Язык",
        "btn_camera_settings": "📷 Настройки камер",
        "btn_admin_ids": "👥 Доступ администраторов",
        "btn_admin_add": "➕ Добавить ID",
        "btn_admin_remove": "➖ Удалить ID",
        "btn_health_check": "🔧 Проверка работы бота",

        "btn_back": "⬅️ Назад",

        "btn_check_room": "👥 Посчитать и отправить",
        "btn_edit_caption": "✏️ Изменить текст",
        "btn_reset_caption": "↩️ Сбросить правку",

        "title_main": "Выберите раздел:",
        "title_schedule": "Расписание:",
        "title_cameras": "Камеры и аудитории:",
        "title_building": "{building} — выберите этаж:",
        "title_building_flat": "{building} — выберите аудиторию:",
        "title_floor": "{floor} — выберите аудиторию:",
        "title_teachers": "Преподаватели:",
        "title_settings": "Настройки:",
        "title_lang": "Выберите язык интерфейса:",
        "title_admin_ids": "Управление администраторами:",
        "title_report": "Выберите пару (1-8) для отчёта:",

        "msg_access_denied": "⛔ Этот бот доступен только администратору. Ваш ID (для запроса доступа): {chat_id}",
        "msg_unrecognized": "Не понял команду. Используйте кнопки ниже 👇 или /menu.",
        "msg_enter_teacher_name": "Введите фамилию преподавателя:",
        "msg_lang_changed": "✅ Язык интерфейса: {lang}",
        "msg_admin_ids": "Разрешённые ID: {ids}",
        "msg_enter_admin_id_add": "Введите Telegram ID нового администратора:",
        "msg_enter_admin_id_remove": "Введите Telegram ID администратора для удаления:",
        "msg_admin_id_invalid": "⚠️ ID должен быть целым числом. Попробуйте ещё раз:",
        "msg_admin_id_added": "✅ ID {chat_id} добавлен.",
        "msg_admin_id_removed": "✅ ID {chat_id} удалён.",
        "msg_admin_master_locked": "⛔ Главного администратора удалить нельзя.",
        "msg_all_sending": "Отправляю фото со всех камер: {floor}...",
        "msg_checking_period": "Запускаю проверку пары {period}...",
        "msg_room_not_configured": "Камера для аудитории {room!r} не настроена.\nНастроены: {rooms}",
        "msg_camera_error": "⚠️ Не удалось получить фото с камеры: {error}",
        "msg_no_lesson_here": "{room}\nВ данный момент урок не проводится.",
        "msg_teacher_no_lesson": "У преподавателя «{query}» сейчас нету урока.",
        "msg_teacher_no_lesson_break": "У преподавателя «{query}» сейчас нету урока (перерыв).",
        "msg_no_camera_for_lesson": "(камера для этой аудитории не настроена)",
        "msg_enter_new_caption": "Пришлите новый текст описания для этого фото:",
        "msg_current_caption_is": "Текущий текст (нажмите и удерживайте, чтобы скопировать):",
        "msg_caption_updated": "Текст обновлён.",
        "btn_change_room": "📷 Другая аудитория",
        "msg_choose_new_room": "Выберите аудиторию, откуда взять новое фото:",
        "btn_cancel": "❌ Отмена",
        "msg_room_changed": "✅ Фото и аудитория обновлены: {room}",

        "title_camera_settings": "Выберите аудиторию для настройки камеры:",
        "btn_period": "Пара {n}",
        "btn_edit_ip": "✏️ IP-адрес",
        "btn_edit_password": "✏️ Пароль",
        "msg_enter_new_ip": "Введите новый IP-адрес камеры (например 10.10.12.164):",
        "msg_enter_new_password": "Введите новый пароль камеры:",
        "msg_ip_invalid": "⚠️ Похоже, это не IP-адрес (нужно вида 10.10.12.164). Попробуйте ещё раз:",
        "msg_camera_updated": "✅ Настройки камеры обновлены.",
        "msg_bot_status_ok": "✅ Бот работает.",
        "msg_bot_uptime": "Аптайм: {h} ч {m} мин",
        "msg_bot_mode": "Режим: {mode}",
        "msg_bot_cameras_count": "Камер настроено: {n}",
        "label_password": "Пароль",

        "title_penalties": "Штрафы:",
        "btn_penalty_period": "📅 Указать период",
        "btn_penalty_add": "➕ Добавить нарушение",
        "btn_penalty_all": "📋 Все нарушения",
        "btn_penalty_by_teacher": "👤 По преподавателю",
        "btn_penalty_by_type": "🏷 По типу нарушения",
        "msg_enter_start_date": "Введите начальную дату периода (ДД.ММ.ГГГГ, например 01.05.2026):",
        "msg_enter_end_date": "Введите конечную дату периода (ДД.ММ.ГГГГ):",
        "msg_date_invalid": "⚠️ Не понял дату. Формат: ДД.ММ.ГГГГ (например 01.05.2026) или «сегодня». Попробуйте ещё раз:",
        "msg_penalty_range_chosen": "Период: {start} — {end}.\nЧто показать?",
        "msg_enter_filter_teacher": "Введите фамилию преподавателя:",
        "msg_choose_violation_type": "Выберите тип нарушения:",
        "msg_enter_violation_date": "Введите дату нарушения (ДД.ММ.ГГГГ или «сегодня»):",
        "msg_enter_violation_period": "Введите номер пары (1-8):",
        "msg_period_invalid": "⚠️ Номер пары должен быть от 1 до 8. Попробуйте ещё раз:",
        "msg_enter_violation_teacher": "Введите фамилию преподавателя:",
        "msg_violation_lesson_found": "Найден урок по расписанию: {subject} [{groups}]. Предмет и группы заполнены автоматически.",
        "msg_violation_lesson_not_found": "Урок по расписанию не найден — заполните данные вручную.",
        "msg_enter_violation_subject": "Введите название предмета:",
        "msg_enter_violation_groups": "Введите группы через / (например ME-23 / ASE-23):",
        "msg_enter_violation_link": "Пришлите ссылку на пост с нарушением (или «-», если ссылки нет):",
        "msg_violation_saved": "✅ Нарушение сохранено: {type} • {date} • пара {period} • {teacher}",
        "msg_duplicate_violation": "⚠️ Нарушение этого типа для пары уже существует:\n{type} • {date} • пара {period} • {teacher}\n\nВсё равно добавить новое? (на это может быть причина)",
        "msg_no_violations": "За выбранный период нарушений не найдено.",
        "msg_violations_summary": "⚠️ Найдено нарушений: {total}\n#ZAMENA: {zamena}\n#TALABALARSONI: {talaba}\n#DARSBARBOD: {darsbarbod}",
        "msg_violation_deleted": "✅ Нарушение удалено.",
        "msg_violation_delete_failed": "⚠️ Не удалось найти нарушение для удаления.",
        "msg_choose_violation_to_delete": "Выберите нарушение для удаления:",
        "msg_no_violations_to_delete": "За выбранный период нарушений не найдено.",
        "msg_cancelled": "Отменено.",
        "btn_today": "📅 Сегодня",
        "btn_yesterday": "📅 Вчера",
        "btn_tomorrow": "📅 Завтра",
        "btn_penalty_delete": "🗑 Удалить нарушение",
        "btn_manage_posts": "📝 Управление постами",
        "msg_duplicate_post": "⚠️ Похоже, этот урок уже был отправлен в группу {minutes} минут назад:\n\n{prev_post}\n\n👥 Предыдущий пост: {prev_students} студентов\n👥 Новый пост: {new_students} студентов\n\nЧто сделать?",
        "btn_replace_post": "🔄 Заменить предыдущий",
        "btn_add_as_new": "➕ Добавить как отдельный",
        "btn_cancel": "❌ Отмена",
        "msg_post_replaced": "✅ Предыдущий пост заменён. Штраф обновлён.",
        "msg_post_added": "✅ Пост добавлен как отдельный нарушение.",
        "msg_choose_post_to_edit": "Выберите пост для редактирования:",
        "msg_no_posts_found": "Постов в группе не найдено за выбранный период.",
        "msg_post_edited": "✅ Пост отредактирован.",
        "msg_post_deleted": "✅ Пост удалён из группы и из списка штрафов.",
        "btn_edit_post": "✏️ Редактировать",
        "btn_delete_post": "🗑 Удалить",
        "msg_welcome": (
            "🎓 <b>TTPU Monitor</b>\n"
            "Система автоматического контроля посещаемости занятий\n\n"
            "Бот подключён к камерам видеонаблюдения университета и нейросети "
            "распознавания людей. По расписанию — и по вашему запросу — он делает "
            "снимок аудитории, подсчитывает число студентов и формирует фотоотчёт "
            "для руководства факультета.\n\n"
            "<b>Разделы:</b>\n"
            "📅 Расписание — план на день/неделю и мгновенный отчёт по любой паре\n"
            "🎥 Камеры-Аудитории — проверка камер и снимок из любой аудитории\n"
            "🧑‍🏫 Преподаватели — кто и где сейчас ведёт занятие\n"
            "⚙️ Настройки — язык интерфейса, параметры камер, статус бота\n\n"
            "Пользуйтесь кнопками ниже 👇 либо командами (полный список — /menu)."
        ),
        "bot_short_description": "Автоматическая проверка посещаемости занятий по камерам видеонаблюдения TTPU.",
        "bot_description": (
            "TTPU Monitor — бот для автоматического контроля посещаемости занятий. "
            "Делает снимки аудиторий по расписанию, считает студентов через нейросеть "
            "и формирует фотоотчёты для руководства. Поддерживает ручную проверку "
            "по кнопкам: расписание, камеры, преподаватели."
        ),
    },
    "en": {
        "btn_schedule": "📅 Schedule",
        "btn_cameras": "🎥 Cameras & Rooms",
        "btn_teachers": "🧑‍🏫 Teachers",
        "btn_penalties": "⚠️ Penalties",
        "btn_settings": "⚙️ Settings",

        "btn_week_schedule": "🗓 Weekly schedule",
        "btn_day_schedule": "📆 Today's schedule",
        "btn_report": "📊 Report",

        "btn_building_a": "🏢 Building A",
        "btn_building_b": "🏢 Building B",
        "btn_building_c": "🏢 Building C",
        "btn_building_mech": "🏢 Mechatronics",
        "btn_check_cams": "📡 Check cameras",

        "btn_floor_4": "Floor 4",
        "btn_floor_3": "Floor 3",
        "btn_floor_2": "Floor 2",
        "btn_floor_1": "Floor 1",
        "btn_all": "📸 ALL",

        "btn_teacher_search": "🔍 Search",
        "btn_teacher_list": "📋 List of teachers",

        "btn_lang": "🌐 Language",
        "btn_camera_settings": "📷 Camera settings",
        "btn_admin_ids": "👥 Administrator access",
        "btn_admin_add": "➕ Add ID",
        "btn_admin_remove": "➖ Remove ID",
        "btn_health_check": "🔧 Bot status check",

        "btn_back": "⬅️ Back",

        "btn_check_room": "👥 Count & send",
        "btn_edit_caption": "✏️ Edit text",
        "btn_reset_caption": "↩️ Undo edit",

        "title_main": "Choose a section:",
        "title_schedule": "Schedule:",
        "title_cameras": "Cameras and rooms:",
        "title_building": "{building} — choose a floor:",
        "title_building_flat": "{building} — choose a room:",
        "title_floor": "{floor} — choose a room:",
        "title_teachers": "Teachers:",
        "title_settings": "Settings:",
        "title_lang": "Choose interface language:",
        "title_admin_ids": "Administrator management:",
        "title_report": "Choose a period (1-8) for the report:",

        "msg_access_denied": "⛔ This bot is only available to the administrator. Your ID (to request access): {chat_id}",
        "msg_unrecognized": "Didn't understand that. Use the buttons below 👇 or /menu.",
        "msg_enter_teacher_name": "Enter the teacher's last name:",
        "msg_lang_changed": "✅ Interface language: {lang}",
        "msg_admin_ids": "Allowed IDs: {ids}",
        "msg_enter_admin_id_add": "Enter the new administrator's Telegram ID:",
        "msg_enter_admin_id_remove": "Enter the administrator's Telegram ID to remove:",
        "msg_admin_id_invalid": "⚠️ The ID must be an integer. Try again:",
        "msg_admin_id_added": "✅ ID {chat_id} added.",
        "msg_admin_id_removed": "✅ ID {chat_id} removed.",
        "msg_admin_master_locked": "⛔ The master administrator cannot be removed.",
        "msg_all_sending": "Sending photos from all cameras: {floor}...",
        "msg_checking_period": "Running check for period {period}...",
        "msg_room_not_configured": "No camera configured for room {room!r}.\nConfigured: {rooms}",
        "msg_camera_error": "⚠️ Could not get a photo from the camera: {error}",
        "msg_no_lesson_here": "{room}\nNo lesson is in progress right now.",
        "msg_teacher_no_lesson": "Teacher «{query}» has no lesson right now.",
        "msg_teacher_no_lesson_break": "Teacher «{query}» has no lesson right now (break).",
        "msg_no_camera_for_lesson": "(no camera configured for this room)",
        "msg_enter_new_caption": "Send the new caption text for this photo:",
        "msg_current_caption_is": "Current text (tap and hold to copy):",
        "msg_caption_updated": "Caption updated.",
        "btn_change_room": "📷 Different room",
        "msg_choose_new_room": "Choose a room to take a new photo from:",
        "btn_cancel": "❌ Cancel",
        "msg_room_changed": "✅ Photo and room updated: {room}",

        "title_camera_settings": "Choose a room to configure its camera:",
        "btn_period": "Period {n}",
        "btn_edit_ip": "✏️ IP address",
        "btn_edit_password": "✏️ Password",
        "msg_enter_new_ip": "Enter the new camera IP address (e.g. 10.10.12.164):",
        "msg_enter_new_password": "Enter the new camera password:",
        "msg_ip_invalid": "⚠️ That doesn't look like an IP address (expected like 10.10.12.164). Try again:",
        "msg_camera_updated": "✅ Camera settings updated.",
        "msg_bot_status_ok": "✅ Bot is running.",
        "msg_bot_uptime": "Uptime: {h}h {m}m",
        "msg_bot_mode": "Mode: {mode}",
        "msg_bot_cameras_count": "Cameras configured: {n}",
        "label_password": "Password",

        "title_penalties": "Penalties:",
        "btn_penalty_period": "📅 Choose a period",
        "btn_penalty_add": "➕ Add a violation",
        "btn_penalty_all": "📋 All violations",
        "btn_penalty_by_teacher": "👤 By teacher",
        "btn_penalty_by_type": "🏷 By violation type",
        "msg_enter_start_date": "Enter the start date of the period (DD.MM.YYYY, e.g. 01.05.2026):",
        "msg_enter_end_date": "Enter the end date of the period (DD.MM.YYYY):",
        "msg_date_invalid": "⚠️ Couldn't parse that date. Format: DD.MM.YYYY (e.g. 01.05.2026) or \"today\". Try again:",
        "msg_penalty_range_chosen": "Period: {start} — {end}.\nWhat should I show?",
        "msg_enter_filter_teacher": "Enter the teacher's last name:",
        "msg_choose_violation_type": "Choose the violation type:",
        "msg_enter_violation_date": "Enter the violation date (DD.MM.YYYY or \"today\"):",
        "msg_enter_violation_period": "Enter the period number (1-8):",
        "msg_period_invalid": "⚠️ Period number must be between 1 and 8. Try again:",
        "msg_enter_violation_teacher": "Enter the teacher's last name:",
        "msg_violation_lesson_found": "Found a matching lesson in the schedule: {subject} [{groups}]. Subject and groups filled in automatically.",
        "msg_violation_lesson_not_found": "No matching lesson found in the schedule — enter the details manually.",
        "msg_enter_violation_subject": "Enter the subject name:",
        "msg_enter_violation_groups": "Enter the groups separated by / (e.g. ME-23 / ASE-23):",
        "msg_enter_violation_link": "Send a link to the post about this violation (or \"-\" if none):",
        "msg_violation_saved": "✅ Violation saved: {type} • {date} • period {period} • {teacher}",
        "msg_duplicate_violation": "⚠️ A violation of this type for this period already exists:\n{type} • {date} • period {period} • {teacher}\n\nAdd it anyway? (There may be a reason for this)",
        "msg_no_violations": "No violations found for the selected period.",
        "msg_violations_summary": "⚠️ Violations found: {total}\n#ZAMENA: {zamena}\n#TALABALARSONI: {talaba}\n#DARSBARBOD: {darsbarbod}",
        "msg_violation_deleted": "✅ Violation deleted.",
        "msg_violation_delete_failed": "⚠️ Could not find a violation to delete.",
        "msg_choose_violation_to_delete": "Choose a violation to delete:",
        "msg_no_violations_to_delete": "No violations found for the selected period.",
        "msg_cancelled": "Cancelled.",
        "btn_today": "📅 Today",
        "btn_yesterday": "📅 Yesterday",
        "btn_tomorrow": "📅 Tomorrow",
        "btn_penalty_delete": "🗑 Delete violation",
        "btn_manage_posts": "📝 Manage posts",
        "btn_edit_post": "✏️ Edit",
        "btn_delete_post": "🗑 Delete",
        "msg_no_posts_found": "No posts found for the selected period.",
        "msg_post_deleted": "✅ Post deleted from group and violations list.",

        "msg_welcome": (
            "🎓 <b>TTPU Monitor</b>\n"
            "Automated class attendance monitoring system\n\n"
            "The bot is connected to the university's CCTV cameras and a people-"
            "detection neural network. On schedule — and on your request — it "
            "takes a snapshot of a classroom, counts the students, and produces "
            "a photo report for department management.\n\n"
            "<b>Sections:</b>\n"
            "📅 Schedule — daily/weekly plan and an instant report for any period\n"
            "🎥 Cameras & Rooms — check cameras and get a photo from any room\n"
            "🧑‍🏫 Teachers — who is teaching where right now\n"
            "⚙️ Settings — interface language, camera settings, bot status\n\n"
            "Use the buttons below 👇 or commands (full list — /menu)."
        ),
        "bot_short_description": "Automated classroom attendance monitoring via TTPU's CCTV cameras.",
        "bot_description": (
            "TTPU Monitor is a bot for automated class attendance monitoring. "
            "It takes snapshots of classrooms on schedule, counts students with "
            "a neural network, and generates photo reports for department "
            "management. Supports manual checks via buttons: schedule, cameras, teachers."
        ),
    },
    "uz": {
        "btn_schedule": "📅 Dars jadvali",
        "btn_cameras": "🎥 Kameralar-Xonalar",
        "btn_teachers": "🧑‍🏫 O'qituvchilar",
        "btn_penalties": "⚠️ Jarimalar",
        "btn_settings": "⚙️ Sozlamalar",

        "btn_week_schedule": "🗓 Haftalik jadval",
        "btn_day_schedule": "📆 Bugungi jadval",
        "btn_report": "📊 Hisobot",

        
        "btn_building_a": "🏢 A bino",
        "btn_building_b": "🏢 B bino",
        "btn_building_c": "🏢 C bino",
        "btn_building_mech": "🏢 Mechatronics",
        "btn_check_cams": "📡 Kameralarni tekshirish",

        "btn_floor_4": "4-qavat",
        "btn_floor_3": "3-qavat",
        "btn_floor_2": "2-qavat",
        "btn_floor_1": "1-qavat",
        "btn_all": "📸 BARCHASI",

        "btn_teacher_search": "🔍 Qidirish",
        "btn_teacher_list": "📋 O'qituvchilar ro'yxati",

        "btn_lang": "🌐 Til",
        "btn_camera_settings": "📷 Kamera sozlamalari",
        "btn_admin_ids": "👥 Administratorlar ruxsati",
        "btn_admin_add": "➕ ID qo'shish",
        "btn_admin_remove": "➖ ID o'chirish",
        "btn_health_check": "🔧 Bot holatini tekshirish",

        "btn_back": "⬅️ Orqaga",

        "btn_check_room": "👥 Hisoblash va yuborish",
        "btn_edit_caption": "✏️ Matnni o'zgartirish",
        "btn_reset_caption": "↩️ O'zgarishni bekor qilish",

        "title_main": "Bo'limni tanlang:",
        "title_schedule": "Dars jadvali:",
        "title_cameras": "Kameralar va xonalar:",
        "title_building": "{building} — qavatni tanlang:",
        "title_building_flat": "{building} — xonani tanlang:",
        "title_floor": "{floor} — xonani tanlang:",
        "title_teachers": "O'qituvchilar:",
        "title_settings": "Sozlamalar:",
        "title_lang": "Interfeys tilini tanlang:",
        "title_admin_ids": "Administratorlarni boshqarish:",
        "title_report": "Hisobot uchun juftlikni tanlang (1-8):",

        "msg_access_denied": "⛔ Ushbu bot faqat administrator uchun mavjud. ID raqamingiz (ruxsat so'rash uchun): {chat_id}",
        "msg_unrecognized": "Tushunmadim. Quyidagi tugmalardan 👇 yoki /menu dan foydalaning.",
        "msg_enter_teacher_name": "O'qituvchining familiyasini kiriting:",
        "msg_lang_changed": "✅ Interfeys tili: {lang}",
        "msg_admin_ids": "Ruxsat berilgan IDlar: {ids}",
        "msg_enter_admin_id_add": "Yangi administratorning Telegram ID raqamini kiriting:",
        "msg_enter_admin_id_remove": "O'chiriladigan administratorning Telegram ID raqamini kiriting:",
        "msg_admin_id_invalid": "⚠️ ID butun son bo'lishi kerak. Qayta urinib ko'ring:",
        "msg_admin_id_added": "✅ ID {chat_id} qo'shildi.",
        "msg_admin_id_removed": "✅ ID {chat_id} o'chirildi.",
        "msg_admin_master_locked": "⛔ Bosh administratorni o'chirib bo'lmaydi.",
        "msg_all_sending": "Barcha kameralardan rasm yuborilmoqda: {floor}...",
        "msg_checking_period": "{period}-juftlik tekshirilmoqda...",
        "msg_room_not_configured": "{room!r} xonasi uchun kamera sozlanmagan.\nSozlangan: {rooms}",
        "msg_camera_error": "⚠️ Kameradan rasm olib bo'lmadi: {error}",
        "msg_no_lesson_here": "{room}\nHozirda dars o'tilmayapti.",
        "msg_teacher_no_lesson": "«{query}» o'qituvchisining hozir darsi yo'q.",
        "msg_teacher_no_lesson_break": "«{query}» o'qituvchisining hozir darsi yo'q (tanaffus).",
        "msg_no_camera_for_lesson": "(bu xona uchun kamera sozlanmagan)",
        "msg_enter_new_caption": "Ushbu rasm uchun yangi matnni yuboring:",
        "msg_current_caption_is": "Joriy matn (nusxa olish uchun bosib turing):",
        "msg_caption_updated": "Matn yangilandi.",
        "btn_change_room": "📷 Boshqa xona",
        "msg_choose_new_room": "Yangi rasm olish uchun xonani tanlang:",
        "btn_cancel": "❌ Bekor qilish",
        "msg_room_changed": "✅ Rasm va xona yangilandi: {room}",

        "title_camera_settings": "Kamerasini sozlash uchun xonani tanlang:",
        "btn_period": "{n}-juftlik",
        "btn_edit_ip": "✏️ IP-manzil",
        "btn_edit_password": "✏️ Parol",
        "msg_enter_new_ip": "Kameraning yangi IP-manzilini kiriting (masalan, 10.10.12.164):",
        "msg_enter_new_password": "Kameraning yangi parolini kiriting:",
        "msg_ip_invalid": "⚠️ Bu IP-manzilga o'xshamayapti (masalan, 10.10.12.164 bo'lishi kerak). Qayta urinib ko'ring:",
        "msg_camera_updated": "✅ Kamera sozlamalari yangilandi.",
        "msg_bot_status_ok": "✅ Bot ishlayapti.",
        "msg_bot_uptime": "Ishlash vaqti: {h} soat {m} daqiqa",
        "msg_bot_mode": "Rejim: {mode}",
        "msg_bot_cameras_count": "Sozlangan kameralar: {n}",
        "label_password": "Parol",

        "title_penalties": "Jarimalar:",
        "btn_penalty_period": "📅 Davrni belgilash",
        "btn_penalty_add": "➕ Buzilish qo'shish",
        "btn_penalty_all": "📋 Barcha buzilishlar",
        "btn_penalty_by_teacher": "👤 O'qituvchi bo'yicha",
        "btn_penalty_by_type": "🏷 Turi bo'yicha",
        "msg_enter_start_date": "Davrning boshlanish sanasini kiriting (KK.OO.YYYY, masalan 01.05.2026):",
        "msg_enter_end_date": "Davrning tugash sanasini kiriting (KK.OO.YYYY):",
        "msg_date_invalid": "⚠️ Sanani tushunmadim. Format: KK.OO.YYYY (masalan 01.05.2026) yoki «bugun». Qayta urinib ko'ring:",
        "msg_penalty_range_chosen": "Davr: {start} — {end}.\nNimani ko'rsatay?",
        "msg_enter_filter_teacher": "O'qituvchining familiyasini kiriting:",
        "msg_choose_violation_type": "Buzilish turini tanlang:",
        "msg_enter_violation_date": "Buzilish sanasini kiriting (KK.OO.YYYY yoki «bugun»):",
        "msg_enter_violation_period": "Juftlik raqamini kiriting (1-8):",
        "msg_period_invalid": "⚠️ Juftlik raqami 1 dan 8 gacha bo'lishi kerak. Qayta urinib ko'ring:",
        "msg_enter_violation_teacher": "O'qituvchining familiyasini kiriting:",
        "msg_violation_lesson_found": "Jadvalda mos dars topildi: {subject} [{groups}]. Fan va guruhlar avtomatik to'ldirildi.",
        "msg_violation_lesson_not_found": "Jadvalda mos dars topilmadi — ma'lumotlarni qo'lda kiriting.",
        "msg_enter_violation_subject": "Fan nomini kiriting:",
        "msg_enter_violation_groups": "Guruhlarni / orqali kiriting (masalan ME-23 / ASE-23):",
        "msg_enter_violation_link": "Buzilish haqidagi postga havolani yuboring (yo'q bo'lsa «-»):",
        "msg_violation_saved": "✅ Buzilish saqlandi: {type} • {date} • {period}-juftlik • {teacher}",
        "msg_duplicate_violation": "⚠️ Bu turdagi buzilish ushbu juftlik uchun allaqachon mavjud:\n{type} • {date} • {period}-juftlik • {teacher}\n\nBaribir qo'shay? (Buning uchun sabablar bo'lishi mumkin)",
        "msg_no_violations": "Tanlangan davr uchun buzilishlar topilmadi.",
        "msg_violations_summary": "⚠️ Topilgan buzilishlar: {total}\n#ZAMENA: {zamena}\n#TALABALARSONI: {talaba}\n#DARSBARBOD: {darsbarbod}",
        "msg_violation_deleted": "✅ Buzilish o'chirildi.",
        "msg_violation_delete_failed": "⚠️ O'chirish uchun buzilish topilmadi.",
        "msg_choose_violation_to_delete": "O'chirish uchun buzilishni tanlang:",
        "msg_no_violations_to_delete": "Tanlangan davr uchun buzilishlar topilmadi.",
        "msg_cancelled": "Bekor qilindi.",
        "btn_today": "📅 Bugun",
        "btn_yesterday": "📅 Kecha",
        "btn_tomorrow": "📅 Ertaga",
        "btn_penalty_delete": "🗑 Buzilishni o'chirish",
        "btn_manage_posts": "📝 Postlarni boshqarish",
        "btn_edit_post": "✏️ Tahrirlash",
        "btn_delete_post": "🗑 O'chirish",
        "msg_no_posts_found": "Tanlangan davr uchun postlar topilmadi.",
        "msg_post_deleted": "✅ Post guruhdan va buzilish ro'yxatidan o'chirildi.",

        "msg_welcome": (
            "🎓 <b>TTPU Monitor</b>\n"
            "Darslarga avtomatik davomat nazorati tizimi\n\n"
            "Bot universitetning videokuzatuv kameralariga va odamlarni aniqlash "
            "neyron tarmog'iga ulangan. Jadval bo'yicha — va sizning so'rovingiz "
            "bilan — u xonaning suratini oladi, talabalar sonini hisoblaydi va "
            "bo'lim rahbariyati uchun fotohisobot tuzadi.\n\n"
            "<b>Bo'limlar:</b>\n"
            "📅 Dars jadvali — kun/hafta rejasi va istalgan juftlik uchun tezkor hisobot\n"
            "🎥 Kameralar-Xonalar — kameralarni tekshirish va istalgan xonadan surat\n"
            "🧑‍🏫 O'qituvchilar — hozir kim va qayerda dars o'tmoqda\n"
            "⚙️ Sozlamalar — interfeys tili, kamera sozlamalari, bot holati\n\n"
            "Quyidagi tugmalardan 👇 yoki buyruqlardan foydalaning (to'liq ro'yxat — /menu)."
        ),
        "bot_short_description": "TTPU videokuzatuv kameralari orqali darslarga avtomatik davomat nazorati.",
        "bot_description": (
            "TTPU Monitor — darslarga avtomatik davomat nazorati uchun bot. Jadval "
            "bo'yicha xonalarning suratini oladi, neyron tarmoq yordamida talabalar "
            "sonini hisoblaydi va bo'lim rahbariyati uchun fotohisobot tuzadi. "
            "Tugmalar orqali qo'lda tekshirish imkoniyati bor: jadval, kameralar, o'qituvchilar."
        ),
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    table = TEXT.get(lang) or TEXT[DEFAULT_LANG]
    s = table.get(key) or TEXT[DEFAULT_LANG].get(key) or key
    return s.format(**kwargs) if kwargs else s
