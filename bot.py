
# maxapi 1.2.2

import asyncio
import secrets
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

from maxapi import Bot, Dispatcher
from maxapi.types import (
    MessageCreated,
    BotStarted,
    MessageButton,
    ButtonsPayload,
    RequestGeoLocationButton,
)

from db import (
    init_db,
    WifiPoint,
    UserRole,
    InviteToken,
    get_nearest_points,
    parse_wifi_line,
)

from states import state_mgr



# НАСТРОЙКИ


def load_env_file(path=".env"):
    """Загружает простые KEY=VALUE настройки из .env без доп. зависимостей."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file()
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан MAX_BOT_TOKEN. Создайте файл .env по образцу .env.example "
        "и укажите токен бота MAX."
    )

# Можно указать несколько ID через запятую: ADMIN_IDS=123,456
ADMIN_IDS = [
    value.strip()
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip()
]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# РАБОТА С РОЛЯМИ


def get_user_roles(user_id):
    roles = (
        UserRole
        .select()
        .where(UserRole.user_id == str(user_id))
    )

    return [role.role for role in roles]


def is_admin(user_id):
    return "admin" in get_user_roles(user_id)


def is_operator(user_id):
    roles = get_user_roles(user_id)

    return (
        "operator" in roles
        or "admin" in roles
    )



# КЛАВИАТУРА


def make_keyboard(buttons):
    """
    Создаёт обычную клавиатуру MAX.

    buttons — список строк:
    [
        ["Кнопка 1"],
        ["Кнопка 2", "Кнопка 3"]
    ]
    """

    rows = []

    for row in buttons:
        rows.append([
            MessageButton(text=text)
            for text in row
        ])

    return ButtonsPayload(buttons=rows).pack()


def get_menu_keyboard(user_id):

    roles = get_user_roles(user_id)

    
    # Администратор
    

    if "admin" in roles:

        return make_keyboard([
            ["Добавить точку"],
            ["Редактировать точку"],
            ["Удалить точку"],
            ["Список точек"],
            ["Создать ссылку на оператора"],
            ["Создать ссылку на администратора"],
            ["Снять оператора"],
            ["Снять администратора"],
            ["Список ролей"],
        ])

    
    # Оператор
    

    if "operator" in roles:

        return make_keyboard([
            ["Добавить точку"],
            ["Редактировать точку"],
            ["Удалить точку"],
            ["Список точек"],
        ])

    # Обычный пользователь
    return None


def get_cancel_keyboard():

    return make_keyboard([
        ["Отмена"]
    ])


def get_confirm_keyboard():

    return make_keyboard([
        ["Да", "Нет"]
    ])
def get_geo_keyboard():
    return ButtonsPayload(
        buttons=[
            [
                RequestGeoLocationButton(
                    text="📍 Отправить геопозицию",
                    quick=True,
                )
            ]
        ]
    ).pack()

# ВСПОМОГАТЕЛЬНОЕ


def get_user_id(message):
    """
    Получаем ID пользователя из сообщения MAX.
    """

    return str(message.sender.user_id)


def get_text(message):
    """
    Получаем текст сообщения.
    """

    if message.body is None:
        return ""

    return message.body.text or ""



# ЗАПУСК БОТА И DEEP-LINK ПРИГЛАШЕНИЯ


def ensure_user_exists(user_id):
    """Создаёт обычную роль, только если у пользователя ещё нет ролей."""
    user_id = str(user_id)
    if not UserRole.select().where(UserRole.user_id == user_id).exists():
        UserRole.create(user_id=user_id, role="user")


async def send_start_response(user_id, chat_id, message=None, payload=None):
    """Общий сценарий старта для события MAX bot_started и /start."""
    user_id = str(user_id)
    ensure_user_exists(user_id)

    if payload:
        token = (
            InviteToken.select()
            .where((InviteToken.token == payload) & (InviteToken.is_used == False))
            .first()
        )
        if not token or datetime.now() - token.created_at >= timedelta(minutes=15):
            text = "Ссылка недействительна или истекла."
            keyboard = get_menu_keyboard(user_id) if is_operator(user_id) else get_geo_keyboard()
            await send_reply(message, chat_id, text, keyboard)
            return

        # Не удаляем остальные роли: по требованиям MAX роли суммируются.
        UserRole.get_or_create(user_id=user_id, role=token.role_to_assign)
        UserRole.get_or_create(user_id=user_id, role="user")
        token.is_used = True
        token.save()

        logging.info("Пользователь %s получил роль %s по приглашению", user_id, token.role_to_assign)
        keyboard = get_menu_keyboard(user_id)
        await send_reply(
            message, chat_id,
            f"Вам назначена роль {token.role_to_assign}.",
            keyboard,
        )
        return

    if is_operator(user_id):
        await send_reply(
            message, chat_id,
            "Добро пожаловать! Используйте меню ниже.",
            get_menu_keyboard(user_id),
        )
    else:
        await send_reply(
            message, chat_id,
            "Отправьте свою геопозицию, и я пришлю 3 ближайшие точки "
            "бесплатного Wi-Fi в Костроме.",
            get_geo_keyboard(),
        )


async def send_reply(message, chat_id, text, keyboard=None):
    """Отправляет ответ и для события BotStarted, и для обычного сообщения."""
    attachments = [keyboard] if keyboard else None
    if message is not None:
        await message.answer(text, attachments=attachments)
    else:
        await bot.send_message(chat_id=chat_id, text=text, attachments=attachments)


@dp.bot_started()
async def bot_started(event: BotStarted):
    # MAX отправляет это событие при нажатии «Начать» и при переходе по deep-link.
    user_id = str(event.user.user_id)
    payload = getattr(event, "payload", None)
    if not isinstance(payload, str):
        payload = None
    await send_start_response(user_id, event.chat_id, payload=payload)


# ГЕОЛОКАЦИЯ


@dp.message_created()
async def handle_message(event: MessageCreated):

    message = event.message

    user_id = get_user_id(message)
    exists = (
        UserRole
        .select()
        .where(UserRole.user_id == user_id)
        .exists()
    )

    if not exists:
        UserRole.create(
            user_id=user_id,
            role="user",
        )

    print("USER ID FROM MAX:", user_id)
    print("ROLES:", get_user_roles(user_id))

    
    # Проверяем, есть ли геолокация
    

    body = message.body

    if body is not None:

        latitude = None
        longitude = None

        if body.attachments:

            location = body.attachments[0]

            latitude = getattr(location, "latitude", None)
            longitude = getattr(location, "longitude", None)

        if latitude is not None and longitude is not None:

            await handle_location(
                message,
                user_id,
                latitude,
                longitude
            )

            return

    
    # Если это текст — обрабатываем текст
    

    text = get_text(message).strip()

    # Любое сообщение без координат попадает в текстовый сценарий,
    # в том числе стикеры/вложения без текста.
    await handle_text(
        message,
        user_id,
        text
    )



# ОБРАБОТКА ГЕОЛОКАЦИИ


async def handle_location(
    message,
    user_id,
    latitude,
    longitude
):

    state, data = state_mgr.get_state(user_id)

    # Если пользователь сейчас вводит данные точки,
    # геолокацию игнорируем.
    if state in [
        "adding_point",
        "editing_get_id"
    ]:
        return

    # Ищем три ближайшие точки
    nearest = get_nearest_points(
        latitude,
        longitude
    )

    if not nearest:

        await message.answer(
            "Точки бесплатного Wi-Fi "
            "пока не добавлены."
        )

        return

    await message.answer(
        "Найдены ближайшие точки Wi-Fi:"
    )

    # Выводим три ближайшие точки
    for i, point in enumerate(nearest, 1):

        if point.distance < 1000:

            distance = (
                f"{point.distance:.0f} м"
            )

        else:

            distance = (
                f"{point.distance / 1000:.2f} км"
            )

        # Ссылка Яндекс.Карт
        maps_link = (
            "https://yandex.ru/maps/?pt="
            f"{point.longitude},{point.latitude}"
            "&z=17&l=map"
        )

        await message.answer(
            f"{i}. {point.name}\n"
            f"Адрес: {point.address}\n"
            f"Расстояние: {distance}\n"
            f"Ссылка: {maps_link}"
        )



# ТЕКСТОВЫЕ СООБЩЕНИЯ


async def handle_text(
    message,
    user_id,
    text
):

    roles = get_user_roles(user_id)

    state, data = state_mgr.get_state(user_id)

    admin = "admin" in roles

    operator = (
        "operator" in roles
        or admin
    )

    
    # ОТМЕНА
    

    if text == "Отмена":

        state_mgr.clear_state(user_id)

        keyboard = get_menu_keyboard(user_id)

        await message.answer(
            "Действие отменено.",
            attachments=[keyboard] if keyboard else None
        )

        return

    
    # ДОБАВЛЕНИЕ ТОЧКИ
    

    if (
        state == "adding_point"
        and operator
    ):

        try:

            data_parsed = parse_wifi_line(text)

            point = WifiPoint.create(
                **data_parsed
            )

            logging.info(
                "Оператор %s добавил точку ID %s",
                user_id,
                point.id
            )

            state_mgr.clear_state(user_id)

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                f"Точка Wi-Fi добавлена.\n"
                f"ID: {point.id}\n"
                f"Название: {point.name}\n"
                f"Адрес: {point.address}.",
                attachments=[keyboard] if keyboard else None
            )

        except ValueError as error:

            await message.answer(
                f"Ошибка: {error}\n"
                "Попробуйте ещё раз "
                "или нажмите «Отмена»."
            )

        return


    # ПОЛУЧЕНИЕ ID ДЛЯ РЕДАКТИРОВАНИЯ
    

    if (
        state == "editing_get_id"
        and operator
    ):

        point = (
            WifiPoint
            .select()
            .where(WifiPoint.id == text)
            .first()
        )

        if not point:

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                f"Точка Wi-Fi с ID {text} "
                "не найдена.",
                attachments=[keyboard] if keyboard else None
            )

            state_mgr.clear_state(user_id)

            return

        state_mgr.set_state(
            user_id,
            "editing_save_data",
            {
                "id": point.id
            }
        )

        current = (
            f"{point.name}; "
            f"{point.address}; "
            f"{point.latitude}; "
            f"{point.longitude}; "
            f"{point.ssid}; "
            f"{point.password or ''}; "
            f"{point.comment or ''}"
        )

        await message.answer(
            "Текущие данные:\n"
            f"{current}\n\n"
            "Отправьте новые данные в формате:\n"
            "Название; Адрес; Широта; Долгота; "
            "SSID; Пароль; Комментарий.",
            attachments=[get_cancel_keyboard()]
        )

        return

    
    # СОХРАНЕНИЕ ИЗМЕНЕНИЙ
    

    if (
        state == "editing_save_data"
        and operator
    ):

        try:

            parsed = parse_wifi_line(text)

            (
                WifiPoint
                .update(**parsed)
                .where(
                    WifiPoint.id == data["id"]
                )
                .execute()
            )

            logging.info(
                "Оператор %s изменил точку ID %s",
                user_id,
                data["id"]
            )

            state_mgr.clear_state(user_id)

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                "Точка Wi-Fi обновлена.",
                attachments=[keyboard] if keyboard else None
            )

        except ValueError as error:

            await message.answer(
                f"Ошибка: {error}\n"
                "Попробуйте ещё раз."
            )

        return

    
    # ПОЛУЧЕНИЕ ID ДЛЯ УДАЛЕНИЯ
    

    if (
        state == "deleting_get_id"
        and operator
    ):

        point = (
            WifiPoint
            .select()
            .where(WifiPoint.id == text)
            .first()
        )

        if not point:

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                f"Точка Wi-Fi с ID {text} "
                "не найдена.",
                attachments=[keyboard] if keyboard else None
            )

            state_mgr.clear_state(user_id)

            return

        state_mgr.set_state(
            user_id,
            "deleting_confirm",
            {
                "id": point.id,
                "name": point.name
            }
        )

        await message.answer(
            f"Удалить точку Wi-Fi "
            f"ID {point.id} — "
            f"«{point.name}»?",
            attachments=[get_confirm_keyboard()]
        )

        return

    
    # ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ
    

    if (
        state == "deleting_confirm"
        and operator
    ):

        if text == "Да":

            (
                WifiPoint
                .delete()
                .where(
                    WifiPoint.id == data["id"]
                )
                .execute()
            )

            logging.info(
                "Оператор %s удалил точку ID %s",
                user_id,
                data["id"]
            )

            state_mgr.clear_state(user_id)

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                "Точка Wi-Fi удалена.",
                attachments=[keyboard] if keyboard else None
            )

            return

        if text == "Нет":

            state_mgr.clear_state(user_id)

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                "Удаление отменено.",
                attachments=[keyboard] if keyboard else None
            )

            return

        await message.answer(
            "Нажмите «Да» или «Нет»."
        )

        return


    # МЕНЮ ОПЕРАТОРА
    

    if text == "Добавить точку":

        if not operator:

            await message.answer(
                "Недостаточно прав."
            )

            return

        state_mgr.set_state(
            user_id,
            "adding_point"
        )

        await message.answer(
            "Добавление точки Wi-Fi.\n\n"
            "Отправьте данные одной строкой:\n"
            "Название; Адрес; Широта; Долгота; "
            "SSID; Пароль; Комментарий\n\n"
            "Пароль и комментарий можно оставить пустыми.",
            attachments=[get_cancel_keyboard()]
        )

        return

    
    # Редактирование
    

    if text == "Редактировать точку":

        if not operator:

            await message.answer(
                "Недостаточно прав."
            )

            return

        state_mgr.set_state(
            user_id,
            "editing_get_id"
        )

        await message.answer(
            "Введите ID точки Wi-Fi "
            "для редактирования.",
            attachments=[get_cancel_keyboard()]
        )

        return

    
    # Удаление
    

    if text == "Удалить точку":

        if not operator:

            await message.answer(
                "Недостаточно прав."
            )

            return

        state_mgr.set_state(
            user_id,
            "deleting_get_id"
        )

        await message.answer(
            "Введите ID точки Wi-Fi "
            "для удаления.",
            attachments=[get_cancel_keyboard()]
        )

        return

    
    # Список точек
    

    if text == "Список точек":

        if not operator:

            await message.answer(
                "Недостаточно прав."
            )

            return

        points = list(
            WifiPoint.select()
        )

        if not points:

            await message.answer(
                "Точки Wi-Fi "
                "пока не добавлены."
            )

            return

        result = "Список точек Wi-Fi:\n\n"

        for point in points:

            result += (
                f"ID {point.id}: "
                f"{point.name}\n"
                f"Адрес: {point.address}\n\n"
            )

        await message.answer(result)

        return

    
    # СОЗДАНИЕ ССЫЛКИ НА ОПЕРАТОРА / АДМИНА
    

    if text in [
        "Создать ссылку на оператора",
        "Создать ссылку на администратора"
    ]:

        if not admin:

            await message.answer(
                "Недостаточно прав."
            )

            return

        if "оператора" in text:

            role = "operator"

        else:

            role = "admin"

        # Создаём случайный токен
        token = secrets.token_urlsafe(10)

        InviteToken.create(
            token=token,
            role_to_assign=role
        )

        # Получаем информацию о боте
        bot_info = await bot.get_me()

        # Deep-link MAX
        link = (
            f"https://max.ru/"
            f"{bot_info.username}"
            f"?start={token}"
        )

        await message.answer(
            f"Ссылка для назначения роли "
            f"{role}:\n\n"
            f"{link}\n\n"
            "Ссылка действует 15 минут "
            "и используется один раз."
        )

        return

    
    # СНЯТИЕ ОПЕРАТОРА
    

    if text == "Снять оператора":

        if not admin:

            await message.answer(
                "Недостаточно прав."
            )

            return

        state_mgr.set_state(
            user_id,
            "removing_operator"
        )

        await message.answer(
            "Введите ID пользователя, "
            "у которого нужно снять "
            "роль оператора.",
            attachments=[get_cancel_keyboard()]
        )

        return

    
    # СНЯТИЕ АДМИНИСТРАТОРА
    

    if text == "Снять администратора":

        if not admin:

            await message.answer(
                "Недостаточно прав."
            )

            return

        state_mgr.set_state(
            user_id,
            "removing_admin"
        )

        await message.answer(
            "Введите ID пользователя, "
            "у которого нужно снять "
            "роль администратора.",
            attachments=[get_cancel_keyboard()]
        )

        return

   
    # ОБРАБОТКА СНЯТИЯ ОПЕРАТОРА
    

    if (
        state == "removing_operator"
        and admin
    ):

        target_id = text

        exists = (
            UserRole
            .select()
            .where(
                (UserRole.user_id == target_id)
                & (UserRole.role == "operator")
            )
            .exists()
        )

        if not exists:

            await message.answer(
                f"У пользователя {target_id} "
                "нет роли оператора."
            )

        else:

            (
                UserRole
                .delete()
                .where(
                    (UserRole.user_id == target_id)
                    & (UserRole.role == "operator")
                )
                .execute()
            )

            logging.info(
                "Администратор %s снял operator с %s",
                user_id,
                target_id
            )

            keyboard = get_menu_keyboard(user_id)

            await message.answer(
                f"У пользователя {target_id} "
                "снята роль оператора.",
                attachments=[keyboard] if keyboard else None
            )

        state_mgr.clear_state(user_id)

        return

    
    # ОБРАБОТКА СНЯТИЯ АДМИНИСТРАТОРА
    

    if (
        state == "removing_admin"
        and admin
    ):

        target_id = text

        exists = (
            UserRole
            .select()
            .where(
                (UserRole.user_id == target_id)
                & (UserRole.role == "admin")
            )
            .exists()
        )

        if not exists:

            await message.answer(
                f"У пользователя {target_id} "
                "нет роли администратора."
            )

            state_mgr.clear_state(user_id)

            return

        # Нельзя удалить последнего администратора
        admin_count = (
            UserRole
            .select()
            .where(UserRole.role == "admin")
            .count()
        )

        if admin_count == 1:

            await message.answer(
                "Нельзя снять роль "
                "с последнего администратора."
            )

            state_mgr.clear_state(user_id)

            return

        (
            UserRole
            .delete()
            .where(
                (UserRole.user_id == target_id)
                & (UserRole.role == "admin")
            )
            .execute()
        )

        logging.info(
            "Администратор %s снял admin с %s",
            user_id,
            target_id
        )

        keyboard = get_menu_keyboard(user_id)

        await message.answer(
            f"У пользователя {target_id} "
            "снята роль администратора.",
            attachments=[keyboard] if keyboard else None
        )

        state_mgr.clear_state(user_id)

        return

    
    # СПИСОК РОЛЕЙ
    

    if text == "Список ролей":

        if not admin:

            await message.answer(
                "Недостаточно прав."
            )

            return

        roles = list(
            UserRole.select()
        )

        result = (
            "Список пользователей и ролей:\n\n"
        )

        for role in roles:

            result += (
                f"User {role.user_id}: "
                f"{role.role}\n"
            )

        await message.answer(result)

        return

    
    # НЕРАСПОЗНАННОЕ СООБЩЕНИЕ
    # Если оператор/администратор находится в диалоге ввода, не сбрасываем состояние.
    if state and operator:
        await message.answer(
            "Не удалось обработать сообщение в текущем шаге. "
            "Отправьте ожидаемые текстовые данные или нажмите «Отмена»."
        )
        return

    if not operator:
        await message.answer(
            "Чтобы найти 3 ближайшие точки бесплатного Wi-Fi в Костроме, "
            "отправьте свою геопозицию.",
            attachments=[get_geo_keyboard()],
        )
        return

    keyboard = get_menu_keyboard(user_id)
    await message.answer(
        "Не удалось распознать команду. Выберите действие в меню.",
        attachments=[keyboard] if keyboard else None,
    )



# ЗАПУСК


async def main():

    # Создаём БД и первого администратора
    init_db(ADMIN_IDS)

    print("Бот МАКС запускается...")

    # Если ранее был настроен webhook, события не будут приходить в polling.
    # Для этого проекта используется long polling.
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
