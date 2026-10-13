# local_test.py
# Полная локальная демонстрация бота
# MAX для работы этого файла не требуется.

import secrets
from datetime import datetime, timedelta

from db import (
    UserRole,
    WifiPoint,
    InviteToken,
    init_db,
    get_nearest_points,
    parse_wifi_line,
)


# ------------------------------------------------------------
# НАСТРОЙКИ
# ------------------------------------------------------------

ADMIN_ID = "491388390"


# ------------------------------------------------------------
# РОЛИ
# ------------------------------------------------------------

def show_roles():
    roles = list(UserRole.select())

    print("\n========== РОЛИ ПОЛЬЗОВАТЕЛЕЙ ==========\n")

    if not roles:
        print("Пользователей пока нет.")
        return

    for item in roles:
        print(
            f"ID: {item.user_id} | "
            f"Роль: {item.role}"
        )

    print()


def add_role():
    print("\n========== ВЫДАЧА РОЛИ ==========\n")

    user_id = input("Введите ID пользователя: ").strip()

    if not user_id:
        print("\nID не может быть пустым.\n")
        return

    print("\n1. Оператор")
    print("2. Администратор")

    choice = input("Выберите роль: ").strip()

    if choice == "1":
        role = "operator"
    elif choice == "2":
        role = "admin"
    else:
        print("\nНеизвестная роль.\n")
        return

    # Сначала создаём обычную роль user,
    # если пользователя ещё нет.
    UserRole.get_or_create(
        user_id=user_id,
        role="user"
    )

    UserRole.get_or_create(
        user_id=user_id,
        role=role
    )

    print(
        f"\nПользователю {user_id} "
        f"назначена роль: {role}\n"
    )


def remove_operator():
    print("\n========== СНЯТИЕ ОПЕРАТОРА ==========\n")

    user_id = input("Введите ID пользователя: ").strip()

    exists = UserRole.select().where(
        (UserRole.user_id == user_id)
        & (UserRole.role == "operator")
    ).exists()

    if not exists:
        print("\nУ этого пользователя нет роли оператора.\n")
        return

    UserRole.delete().where(
        (UserRole.user_id == user_id)
        & (UserRole.role == "operator")
    ).execute()

    print(
        f"\nУ пользователя {user_id} "
        "снята роль оператора.\n"
    )


def remove_admin():
    print("\n========== СНЯТИЕ АДМИНИСТРАТОРА ==========\n")

    user_id = input("Введите ID пользователя: ").strip()

    exists = UserRole.select().where(
        (UserRole.user_id == user_id)
        & (UserRole.role == "admin")
    ).exists()

    if not exists:
        print("\nУ этого пользователя нет роли администратора.\n")
        return

    admin_count = UserRole.select().where(
        UserRole.role == "admin"
    ).count()

    # Нельзя удалить последнего администратора.
    if admin_count == 1:
        print(
            "\nНельзя снять роль с последнего администратора.\n"
        )
        return

    UserRole.delete().where(
        (UserRole.user_id == user_id)
        & (UserRole.role == "admin")
    ).execute()

    print(
        f"\nУ пользователя {user_id} "
        "снята роль администратора.\n"
    )


# ------------------------------------------------------------
# ОДНОРАЗОВЫЕ ССЫЛКИ
# ------------------------------------------------------------

def create_invite():
    print("\n========== СОЗДАНИЕ ССЫЛКИ ==========\n")

    print("1. Ссылка на оператора")
    print("2. Ссылка на администратора")

    choice = input("Выберите роль: ").strip()

    if choice == "1":
        role = "operator"
    elif choice == "2":
        role = "admin"
    else:
        print("\nНеизвестная роль.\n")
        return

    token = secrets.token_urlsafe(10)

    InviteToken.create(
        token=token,
        role_to_assign=role
    )

    print("\nСсылка создана!")
    print(f"Роль: {role}")
    print(f"Токен: {token}")
    print("Срок действия: 15 минут")
    print("Использовать можно только один раз.\n")


def use_invite():
    print("\n========== ИСПОЛЬЗОВАНИЕ ССЫЛКИ ==========\n")

    token_text = input("Введите токен: ").strip()
    user_id = input("Введите ID пользователя: ").strip()

    token = InviteToken.select().where(
        (InviteToken.token == token_text)
        & (InviteToken.is_used == False)
    ).first()

    if not token:
        print("\nСсылка недействительна или уже использована.\n")
        return

    # Проверяем срок действия.
    if datetime.now() - token.created_at >= timedelta(minutes=15):
        print("\nСрок действия ссылки истёк.\n")
        return

    role = token.role_to_assign

    # Если пользователя ещё нет,
    # создаём ему обычную роль.
    UserRole.get_or_create(
        user_id=user_id,
        role="user"
    )

    UserRole.get_or_create(
        user_id=user_id,
        role=role
    )

    token.is_used = True
    token.save()

    print(
        f"\nПользователь {user_id} "
        f"получил роль: {role}\n"
    )


# ------------------------------------------------------------
# ТОЧКИ WI-FI
# ------------------------------------------------------------

def show_points():
    points = list(WifiPoint.select())

    print("\n========== СПИСОК ТОЧЕК WI-FI ==========\n")

    if not points:
        print("Точки Wi-Fi пока не добавлены.\n")
        return

    for point in points:
        print(
            f"ID: {point.id}\n"
            f"Название: {point.name}\n"
            f"Адрес: {point.address}\n"
            f"Координаты: "
            f"{point.latitude}, {point.longitude}\n"
            f"SSID: {point.ssid}\n"
            f"Пароль: {point.password or '-'}\n"
            f"Комментарий: {point.comment or '-'}"
        )

        print("-" * 40)

    print()


def add_point():
    print("\n========== ДОБАВЛЕНИЕ ТОЧКИ ==========\n")

    print(
        "Введите данные в формате:\n"
        "Название; Адрес; Широта; Долгота; "
        "SSID; Пароль; Комментарий\n"
    )

    line = input("> ")

    try:
        data = parse_wifi_line(line)

        point = WifiPoint.create(**data)

        print("\nТочка Wi-Fi добавлена!")
        print(f"ID точки: {point.id}\n")

    except ValueError as error:
        print(f"\nОшибка: {error}\n")


def edit_point():
    print("\n========== РЕДАКТИРОВАНИЕ ТОЧКИ ==========\n")

    show_points()

    try:
        point_id = int(
            input("Введите ID точки: ").strip()
        )

        point = WifiPoint.get_or_none(
            WifiPoint.id == point_id
        )

        if not point:
            print("\nТочка не найдена.\n")
            return

        print(
            "\nВведите новые данные:\n"
            "Название; Адрес; Широта; Долгота; "
            "SSID; Пароль; Комментарий\n"
        )

        line = input("> ")

        data = parse_wifi_line(line)

        for key, value in data.items():
            setattr(point, key, value)

        point.save()

        print("\nТочка успешно изменена.\n")

    except ValueError as error:
        print(f"\nОшибка: {error}\n")


def delete_point():
    print("\n========== УДАЛЕНИЕ ТОЧКИ ==========\n")

    show_points()

    try:
        point_id = int(
            input("Введите ID точки: ").strip()
        )

        point = WifiPoint.get_or_none(
            WifiPoint.id == point_id
        )

        if not point:
            print("\nТочка не найдена.\n")
            return

        answer = input(
            f"Удалить «{point.name}»? (да/нет): "
        ).strip().lower()

        if answer == "да":
            point.delete_instance()
            print("\nТочка удалена.\n")
        else:
            print("\nУдаление отменено.\n")

    except ValueError:
        print("\nID должен быть числом.\n")


# ------------------------------------------------------------
# ПОИСК БЛИЖАЙШИХ ТОЧЕК
# ------------------------------------------------------------

def find_nearest():
    print("\n========== ПОИСК БЛИЖАЙШИХ ТОЧЕК ==========\n")

    try:
        latitude = float(
            input("Введите широту пользователя: ")
        )

        longitude = float(
            input("Введите долготу пользователя: ")
        )

        nearest = get_nearest_points(
            latitude,
            longitude
        )

        if not nearest:
            print(
                "\nТочки бесплатного Wi-Fi "
                "пока не добавлены.\n"
            )
            return

        print("\nНайдены 3 ближайшие точки:\n")

        for number, point in enumerate(
            nearest,
            1
        ):

            if point.distance < 1000:
                distance = (
                    f"{point.distance:.0f} м"
                )
            else:
                distance = (
                    f"{point.distance / 1000:.2f} км"
                )

            maps_link = (
                "https://yandex.ru/maps/?pt="
                f"{point.longitude},{point.latitude}"
                "&z=17&l=map"
            )

            print(
                f"{number}. {point.name}\n"
                f"   Адрес: {point.address}\n"
                f"   Расстояние: {distance}\n"
                f"   Яндекс.Карты: {maps_link}\n"
            )


    except ValueError:
        print(
            "\nКоординаты должны быть числами.\n"
        )


# ------------------------------------------------------------
# ГЛАВНОЕ МЕНЮ
# ------------------------------------------------------------

def menu():

    while True:

        print("=" * 55)
        print("           БЕСПЛАТНЫЙ WI-FI КОСТРОМА")
        print("=" * 55)

        print("1. Добавить точку")
        print("2. Список точек")
        print("3. Найти 3 ближайшие точки")
        print("4. Редактировать точку")
        print("5. Удалить точку")
        print("6. Показать роли")
        print("7. Выдать роль")
        print("8. Создать ссылку на роль")
        print("9. Использовать ссылку")
        print("10. Снять оператора")
        print("11. Снять администратора")
        print("0. Выход")

        print()

        choice = input(
            "Выберите действие: "
        ).strip()

        if choice == "1":
            add_point()

        elif choice == "2":
            show_points()

        elif choice == "3":
            find_nearest()

        elif choice == "4":
            edit_point()

        elif choice == "5":
            delete_point()

        elif choice == "6":
            show_roles()

        elif choice == "7":
            add_role()

        elif choice == "8":
            create_invite()

        elif choice == "9":
            use_invite()

        elif choice == "10":
            remove_operator()

        elif choice == "11":
            remove_admin()

        elif choice == "0":
            print("\nВыход из программы.")
            break

        else:
            print(
                "\nНеизвестная команда.\n"
            )


# ------------------------------------------------------------
# ЗАПУСК
# ------------------------------------------------------------

if __name__ == "__main__":

    # Создаём таблицы и добавляем администратора.
    init_db([ADMIN_ID])

    print()
    print("Локальный режим бота запущен.")
    print("MAX для работы этого режима не требуется.")
    print()

    menu()