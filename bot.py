
# maxapi 1.2.2

import asyncio
import secrets
import logging
from datetime import datetime, timedelta

from maxapi import Bot, Dispatcher
from maxapi.types import (
    MessageCreated,
    CommandStart,
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


# ТОКЕЕЕЕЕЕЕЕЕЕЕН
BOT_TOKEN = " "

# ВАШЕ ID администратора
ADMIN_IDS = [
    " "
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



# /START


@dp.message_created(CommandStart())
async def start_command(event: MessageCreated):

    message = event.message

    user_id = get_user_id(message)

    # Получаем текст команды.
    # Например:
    # /start
    # /start ABC123
    text = get_text(message)

    parts = text.split(maxsplit=1)

    args = ""

    if len(parts) > 1:
        args = parts[1].strip()

    
    # Если пользователя ещё нет — создаём обычного user
    

    exists = (
        UserRole
        .select()
        .where(UserRole.user_id == user_id)
        .exists()
    )

    if not exists:

        UserRole.create(
            user_id=user_id,
            role="user"
        )

    
    # DEEP-LINK
    

    if args:

        token = (
            InviteToken
            .select()
            .where(
                (InviteToken.token == args)
                & (InviteToken.is_used == False)
            )
            .first()
        )

        
        # Проверяем токен
        

        if token:

            # Ссылка действует 15 минут
            if (
                datetime.now() - token.created_at
                < timedelta(minutes=15)
            ):

                # Удаляем старые operator/admin роли
                (
                    UserRole
                    .delete()
                    .where(
                        (UserRole.user_id == user_id)
                        & (UserRole.role != "user")
                    )
                    .execute()
                )

                # Выдаём новую роль
                UserRole.get_or_create(
                    user_id=user_id,
                    role=token.role_to_assign
                )

                # user сохраняем
                UserRole.get_or_create(
                    user_id=user_id,
                    role="user"
                )

                # Ссылка использована
                token.is_used = True
                token.save()

                logging.info(
                    "Пользователь %s получил роль %s",
                    user_id,
                    token.role_to_assign
                )

                keyboard = get_menu_keyboard(user_id)

                await message.answer(
                    f"Вам назначена роль "
                    f"{token.role_to_assign}.",
                    attachments=[keyboard] if keyboard else None
                )

                return

        await message.answer(
            "Ссылка недействительна или истекла."
        )

        return

    
    # ОБЫЧНЫЙ /START
    
    roles = get_user_roles(user_id)

    # Только обычный пользователь
    if roles == ["user"]:

        keyboard = ButtonsPayload(
            buttons=[
                [
                    RequestGeoLocationButton(
                        text="📍 Отправить геопозицию",
                        quick=True
                    )
                ]
            ]
        ).pack()

        await message.answer(
            "Отправьте свою геолокацию, "
            "и я пришлю 3 ближайшие точки "
            "бесплатного Wi-Fi в Костроме.",
            attachments=[keyboard]
        )

        return

    # Оператор / администратор
    keyboard = get_menu_keyboard(user_id)

    await message.answer(
        "Добро пожаловать! "
        "Используйте меню ниже.",
        attachments=[keyboard] if keyboard else None
    )



# ГЕОЛОКАЦИЯ


@dp.message_created()
async def handle_message(event: MessageCreated):

    message = event.message

    user_id = get_user_id(message)

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

    if text:

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

    
    # НЕРАСПОЗНАННЫЙ ТЕКСТ
    

    await message.answer(
        "Не удалось распознать команду.\n"
        "Если вы хотите найти Wi-Fi, "
        "отправьте свою геолокацию."
    )



# ЗАПУСК


async def main():

    # Создаём БД и первого администратора
    init_db(ADMIN_IDS)

    print("Бот МАКС запускается...")

    # Запускаем polling
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())