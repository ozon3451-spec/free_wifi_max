# db.py
# База данных бота бесплатного Wi-Fi

import math
import logging
from datetime import datetime
from peewee import *



# Логи операторов и админов

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_actions.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)




db = SqliteDatabase("wifi_bot.db")


# Базовая модель


class BaseModel(Model):
    class Meta:
        database = db



# Один пользователь может иметь несколько ролей.


class UserRole(BaseModel):
    user_id = CharField()
    role = CharField()  

    class Meta:
        primary_key = CompositeKey("user_id", "role")



# Точки Wi-Fi


class WifiPoint(BaseModel):
    name = CharField()
    address = CharField()
    latitude = FloatField()
    longitude = FloatField()
    ssid = CharField()
    password = CharField(null=True)
    comment = TextField(null=True)



# Одноразовые ссылки для выдачи ролей


class InviteToken(BaseModel):
    token = CharField(unique=True)
    role_to_assign = CharField()  # operator / admin
    created_at = DateTimeField(default=datetime.now)
    is_used = BooleanField(default=False)



# Создание базы данных


def init_db(admin_ids):
    db.connect(reuse_if_open=True)

    db.create_tables([
        UserRole,
        WifiPoint,
        InviteToken
    ])

    # Добавляем администраторов из ADMIN_IDS
    for admin_id in admin_ids:
        UserRole.get_or_create(
            user_id=str(admin_id),
            role="user"
        )

        UserRole.get_or_create(
            user_id=str(admin_id),
            role="admin"
        )



# Расстояние между двумя координатами
# Формула гаверсинусов


def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return R * c



# Поиск трёх ближайших точек


def get_nearest_points(user_lat, user_lon):
    points = list(WifiPoint.select())

    if not points:
        return []

    for point in points:
        point.distance = calculate_distance(
            user_lat,
            user_lon,
            point.latitude,
            point.longitude
        )

    points.sort(key=lambda x: x.distance)

    return points[:3]



# Разбор строки с данными Wi-Fi точки
#
# Формат:
#
# Название; Адрес; Широта; Долгота;
# SSID; Пароль; Комментарий


def parse_wifi_line(line):
    parts = [
        p.strip()
        for p in line.split(";")
    ]

    if len(parts) != 7:
        raise ValueError(
            "нужно указать ровно 7 полей через ';'"
        )

    (
        name,
        address,
        lat,
        lon,
        ssid,
        password,
        comment
    ) = parts

    if not name:
        raise ValueError(
            "Название не может быть пустым"
        )

    if not address:
        raise ValueError(
            "Адрес не может быть пустым"
        )

    if not ssid:
        raise ValueError(
            "SSID не может быть пустым"
        )

    try:
        latitude = float(lat)
        longitude = float(lon)
    except ValueError:
        raise ValueError(
            "Широта и долгота должны быть числами"
        )

    return {
        "name": name,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "ssid": ssid,
        "password": password or None,
        "comment": comment or None
    }