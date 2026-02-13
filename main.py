import telebot
from telebot import types
import json
import os
import shutil
import uuid
import tempfile
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time
from PIL import Image, ImageFilter
import threading
import logging
from cryptography.fernet import Fernet

# Конфигурация
BOT_TOKEN = '8590062777:AAH1MxOo8a1jQQ_pUilHuIoGPdOjkeTkzb4'
ADMIN_IDS = [823833886, 8583562980, 763028520]  # ID администраторов
NOTIFICATION_CHATS = [-5206657753]  # Чаты для уведомлений о покупках

bot = telebot.TeleBot(BOT_TOKEN)


# ---------- ШИФРОВАНИЕ ----------
from cryptography.fernet import Fernet
import tempfile

ENCRYPTION_KEY_FILE = 'encryption.key'  # файл с ключом шифрования

def get_encryption_key() -> bytes:
    """Загружает или генерирует ключ шифрования."""
    if os.path.exists(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, 'wb') as f:
            f.write(key)
        # Установите права доступа, чтобы только бот мог читать (опционально)
        return key

cipher = Fernet(get_encryption_key())

def encrypt_file(input_path: str, output_path: str = None) -> str:
    """Шифрует файл и сохраняет результат. Если output_path не указан, заменяет исходный."""
    with open(input_path, 'rb') as f:
        data = f.read()
    encrypted = cipher.encrypt(data)
    out = output_path or input_path
    with open(out, 'wb') as f:
        f.write(encrypted)
    return out

def decrypt_file(input_path: str, output_path: str = None) -> str:
    """Дешифрует файл и сохраняет во временный файл, если output_path не указан."""
    with open(input_path, 'rb') as f:
        encrypted = f.read()
    decrypted = cipher.decrypt(encrypted)
    if output_path:
        out = output_path
    else:
        # Создаём временный файл с тем же расширением
        ext = os.path.splitext(input_path)[1]
        fd, out = tempfile.mkstemp(suffix=ext)
        os.close(fd)
    with open(out, 'wb') as f:
        f.write(decrypted)
    return out

def encrypt_data(data: bytes) -> bytes:
    """Шифрует данные в памяти."""
    return cipher.encrypt(data)

def decrypt_data(encrypted: bytes) -> bytes:
    """Дешифрует данные."""
    return cipher.decrypt(encrypted)

def send_decrypted_media(chat_id, media_path, media_type, caption=None, protect=True):
    """Расшифровывает файл, проверяет его целостность, отправляет и удаляет временную копию."""
    temp_path = None
    try:
        # Расшифровываем во временный файл
        temp_path = decrypt_file(media_path)
        
        # Для фото дополнительно проверяем, что это действительно изображение
        if media_type == 'photo':
            try:
                with Image.open(temp_path) as img:
                    # Принудительно загружаем, чтобы поймать ошибку
                    img.verify()
                # После verify нужно reopen, т.к. verify портит файл
                with Image.open(temp_path) as img:
                    pass
            except Exception as e:
                raise ValueError(f"Файл не является корректным изображением: {e}")
        
        # Отправляем
        with open(temp_path, 'rb') as f:
            if media_type == 'photo':
                msg = bot.send_photo(chat_id, f, caption=caption, protect_content=protect)
            else:
                msg = bot.send_video(chat_id, f, caption=caption, protect_content=protect)
        return msg
    except Exception as e:
        print(f"Ошибка при отправке расшифрованного медиа: {e}")
        raise  # пробрасываем дальше для обработки в вызывающей функции
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
    

# Файлы для хранения данных
USERS_FILE = 'users.json'
PRODUCTS_FILE = 'products.json'
ORDERS_FILE = 'orders.json'
TASKS_FILE = 'tasks.json'
CHANNELS_FILE = 'channels.json'
USED_LINKS_FILE = 'used_links.json'
VOTING_FILE = 'voting.json'
MODELS_DATA_FILE = 'models_data.json'

# ПАПКИ С КОНТЕНТОМ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
MODELS_PREVIEW_DIR = os.path.join(MODELS_DIR, "_previews")

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(MODELS_PREVIEW_DIR, exist_ok=True)

# Загрузка данных
def load_data(filename: str, default: dict = None):
    if default is None:
        default = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_data(filename: str, data: dict):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_data(USERS_FILE, {})
# Добавляем поле purchased_products для всех пользователей (совместимость)
for uid, user in users.items():
    if 'purchased_products' not in user:
        user['purchased_products'] = []
save_data(USERS_FILE, users)

products = load_data(PRODUCTS_FILE, {})
orders = load_data(ORDERS_FILE, {})
used_links = load_data(USED_LINKS_FILE, {})

tasks_data = load_data(TASKS_FILE, {})
if not tasks_data:
    tasks_data = {
        'daily_login': {
            'name': 'Ежедневный вход',
            'description': 'Зайдите в бота каждый день',
            'points': 20,
            'type': 'daily',
            'cooldown_hours': 24
        },
        'referral': {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }
    }
    save_data(TASKS_FILE, tasks_data)

tasks = tasks_data
channels = load_data(CHANNELS_FILE, {})

# ---------- ДАННЫЕ МОДЕЛЕЙ (описания) ----------
def load_models_data():
    default = {}
    return load_data(MODELS_DATA_FILE, default)

def save_models_data(data):
    save_data(MODELS_DATA_FILE, data)

models_data = load_models_data()

# ---------- МОДЕЛЬ НЕДЕЛИ (ГОЛОСОВАНИЕ) ----------
def load_voting():
    default = {
        'is_active': False,
        'week_start': None,
        'candidates': {},
        'voted_users': [],
        'winner_model': None,
        'discount_until': None,
        'manual_discounts': {}
    }
    return load_data(VOTING_FILE, default)

def save_voting(data):
    save_data(VOTING_FILE, data)

voting_data = load_voting()

def get_available_models():
    """Список имён папок в MODELS_DIR (исключая _previews)"""
    if os.path.exists(MODELS_DIR):
        return [d for d in os.listdir(MODELS_DIR)
                if os.path.isdir(os.path.join(MODELS_DIR, d)) and not d.startswith('_')]
    return []

def start_new_voting_period(start_date):
    global voting_data
    voting_data = {
        'is_active': True,
        'week_start': start_date.isoformat(),
        'candidates': {},
        'voted_users': [],
        'winner_model': None,
        'discount_until': None,
        'manual_discounts': voting_data.get('manual_discounts', {})
    }
    for model in get_available_models():
        voting_data['candidates'][model] = 0
    save_voting(voting_data)

def ensure_voting_week():
    global voting_data
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())

    if not voting_data.get('is_active'):
        start_new_voting_period(monday)
        return

    week_start_str = voting_data.get('week_start')
    if week_start_str:
        try:
            week_start = datetime.fromisoformat(week_start_str).date()
            if week_start != monday:
                finish_voting(force=False)
                start_new_voting_period(monday)
        except:
            start_new_voting_period(monday)
    else:
        start_new_voting_period(monday)

def finish_voting(force=True):
    global voting_data
    if not voting_data['candidates']:
        winner = "Нет кандидатов"
    else:
        winner = max(voting_data['candidates'].items(), key=lambda x: x[1])[0]

    if force and winner != "Нет кандидатов":
        voting_data['winner_model'] = winner
        next_monday = datetime.now().date() + timedelta(days=(7 - datetime.now().weekday()))
        voting_data['discount_until'] = next_monday.isoformat()
        notify_all_users_about_winner(winner)

    voting_data['is_active'] = False
    save_voting(voting_data)
    return winner

def notify_all_users_about_winner(model_name):
    caption = f"🏆 Модель недели – {model_name}!\n\nПоздравляем! На следующей неделе на все товары этой модели действует скидка 15% 🎉"
    photo_path = get_model_preview_path(model_name)

    for user_id in users.keys():
        try:
            if photo_path and os.path.exists(photo_path):
                with open(photo_path, 'rb') as photo:
                    bot.send_photo(int(user_id), photo, caption=caption, protect_content=True)
            else:
                bot.send_message(int(user_id), caption)
            time.sleep(0.05)
        except:
            pass

# Функции для работы с фото и описанием моделей
def get_model_preview_path(model_name):
    possible_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    for ext in possible_extensions:
        path = os.path.join(MODELS_PREVIEW_DIR, f"{model_name}{ext}")
        if os.path.exists(path):
            return path
    return None

def save_model_preview(model_name, file_id):
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ext = os.path.splitext(file_info.file_path)[1] or '.jpg'
        filename = f"{model_name}{ext}"
        save_path = os.path.join(MODELS_PREVIEW_DIR, filename)
        with open(save_path, 'wb') as f:
            f.write(downloaded_file)
        return save_path
    except Exception as e:
        print(f"Ошибка сохранения фото модели: {e}")
        return None

def delete_model_preview(model_name):
    path = get_model_preview_path(model_name)
    if path:
        os.remove(path)
        return True
    return False

def get_model_description(model_name):
    return models_data.get(model_name, {}).get('description', '')

def set_model_description(model_name, description):
    if model_name not in models_data:
        models_data[model_name] = {}
    models_data[model_name]['description'] = description
    save_models_data(models_data)

# Скидки
def get_product_price_with_discount(product):
    price_stars = product['price_stars']
    discount = 0

    if voting_data.get('winner_model') and voting_data.get('discount_until'):
        until = datetime.fromisoformat(voting_data['discount_until']).date()
        if product.get('model_name') == voting_data['winner_model'] and datetime.now().date() <= until:
            discount = 15

    manual = voting_data.get('manual_discounts', {}).get(product.get('model_name'), 0)
    if manual > discount:
        discount = manual

    if discount:
        price_stars_disc = int(price_stars * (100 - discount) / 100)
        price_points_disc = price_stars_disc * 2
        return price_stars_disc, price_points_disc, discount
    else:
        return price_stars, price_stars * 2, 0

def get_discounted_products():
    discounted = []
    for pid, prod in products.items():
        _, _, disc = get_product_price_with_discount(prod)
        if disc > 0:
            discounted.append(prod)
    return discounted

# Модели данных
class Product:
    def __init__(self, product_id: str, name: str, description: str,
                 price_stars: int, category: str, model_name: str = None,
                 media_files: List[str] = None, media_type: str = None,
                 cover_file: str = None, purchase_count: int = 0,
                 channel_id: str = None, channel_invite_link: str = None,
                 welcome_message: str = None, blur_photos: bool = False,
                 auto_delete: bool = False, auto_delete_minutes: int = 15):
        self.id = product_id
        self.name = name
        self.description = description
        self.price_stars = price_stars
        self.category = category
        self.model_name = model_name
        self.media_files = media_files or []
        self.media_type = media_type
        self.cover_file = cover_file
        self.purchase_count = purchase_count
        self.channel_id = channel_id
        self.channel_invite_link = channel_invite_link
        self.welcome_message = welcome_message
        self.is_channel_access = bool(channel_id or channel_invite_link)
        self.blur_photos = blur_photos
        self.auto_delete = auto_delete
        self.auto_delete_minutes = auto_delete_minutes

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price_stars': self.price_stars,
            'category': self.category,
            'model_name': self.model_name,
            'media_files': self.media_files,
            'media_type': self.media_type,
            'cover_file': self.cover_file,
            'purchase_count': self.purchase_count,
            'channel_id': self.channel_id,
            'channel_invite_link': self.channel_invite_link,
            'welcome_message': self.welcome_message,
            'is_channel_access': self.is_channel_access,
            'blur_photos': self.blur_photos,
            'auto_delete': self.auto_delete,
            'auto_delete_minutes': self.auto_delete_minutes,
            'created_at': datetime.now().isoformat()
        }

class Order:
    def __init__(self, order_id: str, user_id: int, product_id: str,
                 status: str = 'pending', invoice_message_id: int = None,
                 payment_method: str = 'stars', price_paid: int = None):
        self.id = order_id
        self.user_id = user_id
        self.product_id = product_id
        self.status = status
        self.invoice_message_id = invoice_message_id
        self.payment_method = payment_method
        self.price_paid = price_paid
        self.created_at = datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'product_id': self.product_id,
            'status': self.status,
            'invoice_message_id': self.invoice_message_id,
            'payment_method': self.payment_method,
            'price_paid': self.price_paid,
            'created_at': self.created_at
        }

class User:
    def __init__(self, user_id: int, username: str = None, first_name: str = None):
        self.id = user_id
        self.username = username
        self.first_name = first_name
        self.balance_stars = 0
        self.points = 0
        self.referral_code = str(uuid.uuid4())[:8]
        self.referred_by = None
        self.orders = []
        self.daily_login_streak = 0
        self.last_daily_login = None
        self.completed_tasks = []
        self.purchased_products = []  # новые купленные товары
        self.created_at = datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'first_name': self.first_name,
            'balance_stars': self.balance_stars,
            'points': self.points,
            'referral_code': self.referral_code,
            'referred_by': self.referred_by,
            'orders': self.orders,
            'daily_login_streak': self.daily_login_streak,
            'last_daily_login': self.last_daily_login,
            'completed_tasks': self.completed_tasks,
            'purchased_products': self.purchased_products,
            'created_at': self.created_at
        }
    
    # Утилиты
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in str(text)])

def generate_product_id():
    return f"prod_{len(products) + 1}_{int(time.time())}"

def generate_order_id():
    return f"order_{len(orders) + 1}_{int(time.time())}"

def save_file_from_telegram(file_id: str, file_type: str, model_name: str, product_id: str, subfolder: str = None):
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_extension = file_info.file_path.split('.')[-1]
        unique_filename = f"{product_id}_{uuid.uuid4().hex[:8]}.{file_extension}"

        if subfolder:
            save_path = os.path.join(MODELS_DIR, model_name, subfolder, unique_filename)
        elif file_type == 'photo':
            save_path = os.path.join(MODELS_DIR, model_name, "photo", unique_filename)
        elif file_type == 'video':
            save_path = os.path.join(MODELS_DIR, model_name, "video", unique_filename)
        else:
            return None

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Шифруем данные и сохраняем
        encrypted_data = encrypt_data(downloaded_file)
        with open(save_path, 'wb') as new_file:
            new_file.write(encrypted_data)

        return unique_filename
    except Exception as e:
        print(f"Ошибка сохранения файла: {e}")
        return None

def send_product_to_user(user_id, product_id, order_id):
    if product_id not in products:
        print(f"Товар {product_id} не найден")
        return

    product = products[product_id]
    order = orders.get(order_id)
    if not order:
        print(f"Заказ {order_id} не найден")
        return

    payment_method = order.get('payment_method')
    price_paid = order.get('price_paid', product['price_stars'])
    delivery_successful = True  # флаг успешной доставки всех файлов

    # Подтверждение оплаты (не влияет на доставку)
    try:
        bot.send_message(
            user_id,
            f"✅ Покупка успешно оплачена!\n\n"
            f"📦 Товар: {product['name']}\n"
            f"💰 Цена: {price_paid} Stars\n"
            f"📋 Номер заказа: {order_id}",
            protect_content=True
        )
    except Exception as e:
        print(f"Не удалось отправить подтверждение оплаты: {e}")

    # --- Доставка контента ---
    try:
        if product.get('is_channel_access', False):
            one_time_link = create_one_time_link(product_id, user_id)
            custom_welcome = product.get('welcome_message')
            welcome_message = (
                f"{custom_welcome}\n\n"
                f"🔗 Ваша одноразовая ссылка для доступа:\n\n{one_time_link}\n\n"
                f"⚠️ Внимание:\n• Ссылка действует только один раз\n• Никому не передавайте ссылку\n"
                f"• После использования ссылка станет неактивной\n\n"
                f"👤 Для активации доступа просто нажмите на ссылку выше."
            ) if custom_welcome else (
                f"🎉 Добро пожаловать в канал!\n\n"
                f"🔗 Ваша одноразовая ссылка для доступа:\n\n{one_time_link}\n\n"
                f"⚠️ Внимание:\n• Ссылка действует только один раз\n• Никому не передавайте ссылку\n"
                f"• После использования ссылка станет неактивной\n\n"
                f"👤 Для активации доступа просто нажмите на ссылку выше."
            )
            try:
                bot.send_message(user_id, welcome_message, protect_content=True)
                notify_admins_about_channel_purchase(user_id, product, order_id, one_time_link)
            except Exception as e:
                print(f"Ошибка отправки сообщения с доступом в канал: {e}")
                delivery_successful = False

        elif product.get('media_files'):
            model_path = os.path.join(MODELS_DIR, product['model_name'])
            # Проверим существование папки модели
            if not os.path.exists(model_path):
                print(f"Папка модели не найдена: {model_path}")
                delivery_successful = False
            else:
                # Предупреждение
                warning_text = f"📦 Доставка товара: {product['name']}"
                if product.get('blur_photos', False):
                    warning_text += "\n🔒 Фото размыты для защиты контента"
                if product.get('auto_delete', False):
                    warning_text += f"\n⚠️ Медиафайлы будут автоматически удалены через {product.get('auto_delete_minutes', 15)} минут!"
                try:
                    warning_msg = bot.send_message(user_id, warning_text)
                    if product.get('auto_delete', False):
                        schedule_message_deletion(user_id, warning_msg.message_id, product.get('auto_delete_minutes', 15))
                except Exception as e:
                    print(f"Ошибка отправки предупреждения: {e}")

                # Отправляем каждый медиафайл
                for idx, media_file in enumerate(product['media_files'], start=1):
                    # Правильный путь к зашифрованному файлу
                    media_path = os.path.join(model_path, product['media_type'], media_file)

                    if not os.path.exists(media_path):
                        print(f"Файл не найден: {media_path}")
                        delivery_successful = False
                        break

                    try:
                        if product['media_type'] == 'photo':
                            if product.get('blur_photos', False):
                                temp_clear = decrypt_file(media_path)
                                blurred_path = apply_blur_to_photo(temp_clear, blur_radius=20)
                                with open(blurred_path, 'rb') as photo:
                                    msg = bot.send_photo(user_id, photo, protect_content=True)
                                os.unlink(temp_clear)
                                os.unlink(blurred_path)
                            else:
                                # Используем улучшенную функцию send_decrypted_media
                                msg = send_decrypted_media(user_id, media_path, 'photo', protect=True)
                        else:  # video
                            msg = send_decrypted_media(user_id, media_path, 'video', protect=True)

                        if msg and product.get('auto_delete', False):
                            schedule_message_deletion(user_id, msg.message_id, product.get('auto_delete_minutes', 15))

                    except Exception as e:
                        print(f"Ошибка отправки медиафайла {media_file}: {e}")
                        delivery_successful = False
                        # Уведомляем пользователя о проблеме
                        try:
                            bot.send_message(
                                user_id,
                                f"❌ Не удалось отправить файл {idx}. Пожалуйста, свяжитесь с администратором."
                            )
                        except:
                            pass
                        break  # Прерываем отправку остальных файлов

    except Exception as e:
        print(f"Критическая ошибка в блоке доставки: {e}")
        delivery_successful = False

    # --- Обработка результата доставки ---
    if delivery_successful:
        # Успех
        orders[order_id]['status'] = 'completed'
        orders[order_id]['delivered_at'] = datetime.now().isoformat()
        save_data(ORDERS_FILE, orders)

        # Финальное сообщение
        final_msg = bot.send_message(
            user_id,
            "🎉 Товар успешно доставлен!\n"
            "Спасибо за покупку! 💖\n\n"
            "🔄 Чтобы увидеть обновлённый каталог (без купленных товаров), нажмите /catalog",
            protect_content=True
        )
        if product.get('auto_delete', False):
            schedule_message_deletion(user_id, final_msg.message_id, product.get('auto_delete_minutes', 15))

    else:
        # Неудача – возврат средств (только для очков) и уведомление админов
        orders[order_id]['status'] = 'delivery_failed'
        orders[order_id]['failed_at'] = datetime.now().isoformat()
        save_data(ORDERS_FILE, orders)

        if payment_method == 'points':
            user_id_str = str(user_id)
            if user_id_str in users:
                points_returned = price_paid * 2
                users[user_id_str]['points'] += points_returned
                save_data(USERS_FILE, users)
                bot.send_message(
                    user_id,
                    f"❌ Не удалось доставить товар. "
                    f"Вам возвращено {points_returned}🏆 на баланс.\n"
                    f"Пожалуйста, попробуйте позже или свяжитесь с администратором."
                )
            else:
                bot.send_message(
                    user_id,
                    "❌ Не удалось доставить товар. Свяжитесь с администратором для возврата средств."
                )
        else:  # stars
            bot.send_message(
                user_id,
                "❌ Не удалось доставить товар. Свяжитесь с администратором для возврата Stars."
            )

        # Уведомляем всех админов о сбое
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    f"⚠️ **Сбой доставки товара**\n"
                    f"Пользователь: {user_id}\n"
                    f"Заказ: {order_id}\n"
                    f"Товар: {product['name']}\n"
                    f"Способ оплаты: {payment_method}\n"
                    f"Сумма: {price_paid} Stars / {price_paid*2}🏆\n"
                    f"Требуется ручная проверка."
                )
            except:
                pass
def get_popular_products(limit: int = 5):
    sorted_products = sorted(products.values(), key=lambda x: x.get('purchase_count', 0), reverse=True)
    return sorted_products[:limit]

def get_models_with_products():
    models = {}
    for product_id, product in products.items():
        model_name = product.get('model_name')
        if model_name:
            if model_name not in models:
                models[model_name] = []
            models[model_name].append(product)
    return models

def find_user_by_referral_code(code):
    for user_id, user_data in users.items():
        if user_data.get('referral_code') == code:
            return int(user_id)
    return None

def count_user_referrals(user_id):
    count = 0
    for uid, user_data in users.items():
        if str(user_data.get('referred_by')) == str(user_id):
            count += 1
    return count

def check_daily_login(user_id):
    user_data = users.get(str(user_id))
    if not user_data:
        return

    now = datetime.now()
    today_str = now.date().isoformat()
    last_login_str = user_data.get('last_daily_login')

    if not last_login_str:
        user_data['daily_login_streak'] = 1
        user_data['last_daily_login'] = today_str
        award_daily_login(user_id, 1)
    else:
        last_login = datetime.fromisoformat(last_login_str).date()
        today = now.date()

        if today > last_login:
            delta = (today - last_login).days

            if delta == 1:
                streak = user_data.get('daily_login_streak', 0) + 1
                user_data['daily_login_streak'] = streak
                user_data['last_daily_login'] = today_str
                award_daily_login(user_id, streak)
            elif delta > 1:
                user_data['daily_login_streak'] = 1
                user_data['last_daily_login'] = today_str
                award_daily_login(user_id, 1)

    users[str(user_id)] = user_data
    save_data(USERS_FILE, users)

def award_daily_login(user_id, streak):
    if 'daily_login' not in tasks:
        tasks['daily_login'] = {
            'name': 'Ежедневный вход',
            'description': 'Зайдите в бота каждый день',
            'points': 20,
            'type': 'daily',
            'cooldown_hours': 24
        }
        save_data(TASKS_FILE, tasks)

    base_points = tasks['daily_login']['points']
    streak_bonus = min(streak - 1, 5) * 5
    total_points = base_points + streak_bonus

    if str(user_id) in users:
        users[str(user_id)]['points'] += total_points

        streak_message = ""
        if streak > 1:
            streak_message = f"\n🔥 Серия дней: {streak} (+{streak_bonus} бонус)"

        bot.send_message(
            user_id,
            f"🎁 Ежедневный бонус!\n\n"
            f"Вам начислено: +{total_points}🏆\n"
            f"• База: {base_points}🏆{streak_message}\n\n"
            f"🏆 Общий баланс: {users[str(user_id)]['points']}🏆"
        )
        save_data(USERS_FILE, users)

def apply_blur_to_photo(photo_path, output_path=None, blur_radius=15):
    try:
        with Image.open(photo_path) as img:
            blurred_img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            if output_path:
                blurred_img.save(output_path)
                return output_path
            else:
                temp_path = os.path.join(PROCESSED_DIR, f"blurred_{os.path.basename(photo_path)}")
                blurred_img.save(temp_path)
                return temp_path
    except Exception as e:
        print(f"Ошибка при размытии фото: {e}")
        return photo_path

def schedule_message_deletion(chat_id, message_id, delay_minutes=15):
    def delete_message():
        try:
            bot.delete_message(chat_id, message_id)
            print(f"Сообщение {message_id} удалено через {delay_minutes} минут")
        except Exception as e:
            print(f"Не удалось удалить сообщение {message_id}: {e}")

    timer = threading.Timer(delay_minutes * 60, delete_message)
    timer.daemon = True
    timer.start()

def generate_link_key():
    return uuid.uuid4().hex[:16]

def mark_link_as_used(link_key: str, user_id: int, product_id: str):
    used_links[link_key] = {
        'user_id': user_id,
        'product_id': product_id,
        'used_at': datetime.now().isoformat(),
        'is_used': True
    }
    save_data(USED_LINKS_FILE, used_links)

def is_link_used(link_key: str) -> bool:
    return link_key in used_links and used_links[link_key].get('is_used', False)

def create_one_time_link(product_id: str, user_id: int) -> str:
    link_key = generate_link_key()
    used_links[link_key] = {
        'user_id': user_id,
        'product_id': product_id,
        'created_at': datetime.now().isoformat(),
        'is_used': False
    }
    save_data(USED_LINKS_FILE, used_links)
    return f"https://t.me/{bot.get_me().username}?start=join_{link_key}"


def notify_admins_about_channel_purchase(user_id, product, order_id, one_time_link):
    try:
        user_info = bot.get_chat(user_id)
        username = user_info.username or 'No username'
    except:
        username = 'No username'

    notification_text = (
        f"💰 НОВАЯ ПОКУПКА ДОСТУПА В КАНАЛ\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"🔗 Канал ID: {product.get('channel_id', 'N/A')}\n"
        f"📋 Заказ: {order_id}\n"
        f"🔑 Ключ ссылки: {one_time_link.split('=')[-1] if '=' in one_time_link else 'N/A'}\n"
        f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"⚠️ Ссылка отправлена покупателю."
    )

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, notification_text)
        except:
            pass

    for chat_id in NOTIFICATION_CHATS:
        try:
            bot.send_message(chat_id, notification_text)
        except:
            pass

def award_referral_stars_purchase_bonus(user_id):
    user_data = users.get(str(user_id))
    if not user_data:
        return

    referrer_id = user_data.get('referred_by')
    if not referrer_id or str(referrer_id) not in users:
        return

    if 'referral' not in tasks:
        tasks['referral'] = {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }
        save_data(TASKS_FILE, tasks)

    bonus = tasks['referral'].get('bonus_per_purchase', 0)
    if bonus <= 0:
        return

    users[str(referrer_id)]['points'] += bonus
    save_data(USERS_FILE, users)

    try:
        bot.send_message(
            referrer_id,
            f"🎉 Ваш реферал совершил покупку за Telegram Stars!\n"
            f"Вам начислено +{bonus}🏆\n"
            f"🏆 Текущий баланс: {users[str(referrer_id)]['points']}🏆"
        )
    except:
        pass

    # ---------- УЛУЧШЕННАЯ СТАТИСТИКА ----------
def get_statistics_by_period(period='all'):
    now = datetime.now()

    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'month':
        start_date = now - timedelta(days=30)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:
        start_date = datetime.min

    filtered_orders = []
    for order_id, order in orders.items():
        order_date = datetime.fromisoformat(order['created_at'])
        if order_date >= start_date and order['status'] in ['paid', 'completed']:
            filtered_orders.append(order)

    models_stats = {}
    products_stats = {}
    stars_revenue = 0
    points_revenue = 0
    stars_count = 0
    points_count = 0

    for order in filtered_orders:
        product_id = order['product_id']
        if product_id not in products:
            continue

        product = products[product_id]
        model_name = product.get('model_name', 'Без модели')
        payment_method = order.get('payment_method', 'stars')
        price_paid = order.get('price_paid', product['price_stars'])
        price_points_paid = price_paid * 2

        if model_name not in models_stats:
            models_stats[model_name] = {
                'total_orders': 0,
                'stars_orders': 0,
                'points_orders': 0,
                'stars_revenue': 0,
                'points_revenue': 0,
                'products': {}
            }

        models_stats[model_name]['total_orders'] += 1
        if payment_method == 'stars':
            models_stats[model_name]['stars_orders'] += 1
            models_stats[model_name]['stars_revenue'] += price_paid
            stars_revenue += price_paid
            stars_count += 1
        else:
            models_stats[model_name]['points_orders'] += 1
            models_stats[model_name]['points_revenue'] += price_points_paid
            points_revenue += price_points_paid
            points_count += 1

        if product_id not in products_stats:
            products_stats[product_id] = {
                'name': product['name'],
                'model': model_name,
                'total_orders': 0,
                'stars_orders': 0,
                'points_orders': 0,
                'stars_revenue': 0,
                'points_revenue': 0
            }

        products_stats[product_id]['total_orders'] += 1
        if payment_method == 'stars':
            products_stats[product_id]['stars_orders'] += 1
            products_stats[product_id]['stars_revenue'] += price_paid
        else:
            products_stats[product_id]['points_orders'] += 1
            products_stats[product_id]['points_revenue'] += price_points_paid

    avg_stars_order = stars_revenue / stars_count if stars_count else 0
    avg_points_order = points_revenue / points_count if points_count else 0

    sorted_products_stars = sorted(products_stats.items(),
                                   key=lambda x: x[1]['stars_revenue'], reverse=True)[:5]
    sorted_products_points = sorted(products_stats.items(),
                                    key=lambda x: x[1]['points_revenue'], reverse=True)[:5]

    return {
        'period': period,
        'start_date': start_date,
        'end_date': now,
        'total_orders': len(filtered_orders),
        'models_stats': models_stats,
        'products_stats': products_stats,
        'stars_revenue': stars_revenue,
        'points_revenue': points_revenue,
        'total_revenue': stars_revenue + points_revenue,
        'stars_count': stars_count,
        'points_count': points_count,
        'avg_stars_order': avg_stars_order,
        'avg_points_order': avg_points_order,
        'top_stars_products': sorted_products_stars,
        'top_points_products': sorted_products_points
    }

def format_statistics_message(stats):
    period_names = {
        'week': 'неделю',
        'month': 'месяц',
        'year': 'год',
        'all': 'всё время'
    }

    period_name = period_names.get(stats['period'], stats['period'])

    msg = f"📊 Статистика продаж за {period_name}\n\n"
    msg += f"📦 Всего заказов: {stats['total_orders']}\n"
    msg += f"├─ ⭐ Звёзды: {stats.get('stars_count', 0)} заказов\n"
    msg += f"└─ 🏆 Очки:   {stats.get('points_count', 0)} заказов\n\n"
    msg += f"💰 Выручка:\n"
    msg += f"   ⭐ {stats['stars_revenue']} Stars  (средний чек: {stats['avg_stars_order']:.2f}⭐)\n"
    msg += f"   🏆 {stats['points_revenue']} очков (средний чек: {stats['avg_points_order']:.2f}🏆)\n"
    msg += f"   💰 Всего: {stats['total_revenue']} (⭐ + 🏆)\n\n"

    if stats['models_stats']:
        msg += "👤 Статистика по моделям:\n"
        sorted_models = sorted(stats['models_stats'].items(),
                               key=lambda x: x[1]['total_orders'], reverse=True)[:5]
        for i, (model_name, model_data) in enumerate(sorted_models, 1):
            msg += f"  {i}. {model_name}\n"
            msg += f"     📦 {model_data['total_orders']} зак. "
            msg += f"(⭐{model_data['stars_orders']} / 🏆{model_data['points_orders']})\n"
            msg += f"     ⭐{model_data['stars_revenue']} / 🏆{model_data['points_revenue']}\n"

    if stats.get('top_stars_products'):
        msg += "\n🔥 Топ-5 товаров по звёздам:\n"
        for i, (prod_id, prod) in enumerate(stats['top_stars_products'], 1):
            name = prod['name'][:25] + '…' if len(prod['name']) > 25 else prod['name']
            msg += f"  {i}. {name} – {prod['stars_revenue']}⭐ ({prod['stars_orders']} зак.)\n"

    if stats.get('top_points_products'):
        msg += "\n🏆 Топ-5 товаров по очкам:\n"
        for i, (prod_id, prod) in enumerate(stats['top_points_products'], 1):
            name = prod['name'][:25] + '…' if len(prod['name']) > 25 else prod['name']
            msg += f"  {i}. {name} – {prod['points_revenue']}🏆 ({prod['points_orders']} зак.)\n"

    msg += f"\n📅 Период: {stats['start_date'].strftime('%d.%m.%Y')} – {stats['end_date'].strftime('%d.%m.%Y')}"
    return msg

# ---------- ДЕТАЛЬНАЯ СТАТИСТИКА ПО МОДЕЛЯМ ----------
def get_detailed_models_stats():
    stats = {}
    for order_id, order in orders.items():
        if order['status'] not in ['paid', 'completed']:
            continue
        product_id = order['product_id']
        if product_id not in products:
            continue
        product = products[product_id]
        model = product.get('model_name', 'Без модели')
        if model not in stats:
            stats[model] = {
                'total_sales': 0,
                'stars_earned': 0,
                'points_earned': 0,
                'products': {}
            }
        stats[model]['total_sales'] += 1
        price_paid = order.get('price_paid', product['price_stars'])
        if order['payment_method'] == 'stars':
            stats[model]['stars_earned'] += price_paid
        else:
            stats[model]['points_earned'] += price_paid * 2

        if product_id not in stats[model]['products']:
            stats[model]['products'][product_id] = {
                'name': product['name'],
                'sales': 0,
                'stars': 0,
                'points': 0
            }
        stats[model]['products'][product_id]['sales'] += 1
        if order['payment_method'] == 'stars':
            stats[model]['products'][product_id]['stars'] += price_paid
        else:
            stats[model]['products'][product_id]['points'] += price_paid * 2
    return stats

def handle_channel_join_link(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            return

        param = parts[1]
        if not param.startswith('join_'):
            return

        link_key = param.replace('join_', '')

        if link_key not in used_links:
            bot.send_message(
                message.chat.id,
                "❌ Недействительная ссылка!\n"
                "Ссылка не найдена или уже использована."
            )
            return

        link_data = used_links[link_key]

        if link_data.get('is_used', False):
            bot.send_message(
                message.chat.id,
                "❌ Ссылка уже использована!\n"
                "Одноразовая ссылка может быть использована только один раз."
            )
            return

        if link_data.get('user_id') != message.from_user.id:
            bot.send_message(
                message.chat.id,
                "❌ Эта ссылка предназначена для другого пользователя!\n"
                "Одноразовые ссылки привязаны к конкретному пользователю."
            )
            return

        product_id = link_data.get('product_id')
        if product_id not in products:
            bot.send_message(
                message.chat.id,
                "❌ Товар не найден!\n"
                "Свяжитесь с администратором."
            )
            return

        product = products[product_id]

        if product.get('channel_id'):
            try:
                chat_invite_link = bot.create_chat_invite_link(
                    chat_id=product['channel_id'],
                    member_limit=1,
                    creates_join_request=False,
                    name=f"Одноразовая ссылка для {message.from_user.id}"
                )

                bot.send_message(
                    message.chat.id,
                    f"✅ Доступ к каналу активирован!\n\n"
                    f"🔗 Ваша одноразовая пригласительная ссылка:\n"
                    f"{chat_invite_link.invite_link}\n\n"
                    f"⚠️ Внимание:\n"
                    f"• Ссылка действительна ТОЛЬКО для одного использования\n"
                    f"• После использования ссылка станет неактивной\n"
                    f"• Никому не передавайте эту ссылку\n"
                    f"• Ссылка автоматически деактивируется через 24 часа"
                )

                notify_admins_about_one_time_invite(message.from_user.id, product, chat_invite_link.invite_link)

            except Exception as e:
                print(f"Ошибка создания одноразовой ссылки: {e}")
                if product.get('channel_invite_link'):
                    bot.send_message(
                        message.chat.id,
                        f"✅ Доступ к каналу активирован!\n\n"
                        f"🔗 Пригласительная ссылка:\n"
                        f"{product['channel_invite_link']}\n\n"
                        f"⚠️ Эта ссылка может быть многоразовой. Не передавайте ее другим."
                    )
                else:
                    bot.send_message(
                        message.chat.id,
                        f"✅ Доступ к каналу активирован!\n\n"
                        f"ℹ️ Для получения ссылки на канал свяжитесь с администратором.\n"
                        f"ID канала: {product.get('channel_id', 'не указан')}"
                    )
        else:
            if product.get('channel_invite_link'):
                bot.send_message(
                    message.chat.id,
                    f"✅ Доступ к каналу активирован!\n\n"
                    f"🔗 Пригласительная ссылка:\n"
                    f"{product['channel_invite_link']}\n\n"
                    f"⚠️ Эта ссылка может быть многоразовой. Не передавайте ее другим."
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "✅ Доступ к каналу активирован!\n"
                    "ℹ️ Свяжитесь с администратором для получения ссылки."
                )

        mark_link_as_used(link_key, message.from_user.id, product_id)
        notify_admins_about_link_activation(message.from_user.id, product, link_key)

    except Exception as e:
        print(f"Ошибка обработки ссылки: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при активации доступа.\n"
            "Свяжитесь с администратором."
        )

def notify_admins_about_one_time_invite(user_id, product, invite_link):
    try:
        user_info = bot.get_chat(user_id)
        username = user_info.username or 'No username'
    except:
        username = 'No username'

    notification_text = (
        f"🔗 СОЗДАНА ОДНОРАЗОВАЯ ССЫЛКА ДЛЯ КАНАЛА\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"🔗 Канал ID: {product.get('channel_id', 'N/A')}\n"
        f"🔗 Одноразовая ссылка: {invite_link}\n"
        f"⏰ Создана: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"ℹ️ Ссылка будет деактивирована после первого использования."
    )

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, notification_text)
        except:
            pass

def notify_admins_about_link_activation(user_id, product, link_key):
    try:
        user_info = bot.get_chat(user_id)
        username = user_info.username or 'No username'
    except:
        username = 'No username'

    activation_text = (
        f"🔓 АКТИВАЦИЯ ДОСТУПА В КАНАЛ\n\n"
        f"👤 Пользователь: @{username}\n"
        f"🆔 ID: {user_id}\n"
        f"📦 Товар: {product['name']}\n"
        f"🔗 Канал ID: {product.get('channel_id', 'N/A')}\n"
        f"🔑 Ключ ссылки: {link_key}\n"
        f"⏰ Время активации: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"✅ Ссылка успешно активирована и помечена как использованная."
    )

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, activation_text)
        except:
            pass

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id

    ensure_voting_week()

    if len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith('join_'):
            handle_channel_join_link(message)
            return

    referral_code = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]

    if str(user_id) not in users:
        user = User(
            user_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )

        if referral_code and not referral_code.startswith('join_'):
            referrer_id = find_user_by_referral_code(referral_code)
            if referrer_id:
                user.referred_by = referrer_id
                if str(referrer_id) in users:
                    if 'referral' not in tasks:
                        tasks['referral'] = {
                            'name': 'Реферальная система',
                            'description': 'Пригласите друга по своей реферальной ссылке',
                            'points': 50,
                            'type': 'one_time',
                            'bonus_per_purchase': 20
                        }
                        save_data(TASKS_FILE, tasks)

                    users[str(referrer_id)]['points'] += tasks['referral']['points']
                    save_data(USERS_FILE, users)

                    try:
                        bot.send_message(
                            referrer_id,
                            f"🎉 По вашей ссылке зарегистрировался новый пользователь!\n"
                            f"Вам начислено +{tasks['referral']['points']} 🏆!"
                        )
                    except:
                        pass

        users[str(user_id)] = user.to_dict()
        save_data(USERS_FILE, users)
        check_daily_login(user_id)
    else:
        check_daily_login(user_id)

    try:
        welcome_banner = open('welcome.jpg', 'rb')
    except FileNotFoundError:
        welcome_banner = None

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('🛍️ Каталог')
    keyboard.add('🥷 Мой профиль', '🎯 Задания')
    keyboard.add('👥 Реферальная система', 'ℹ️ Помощь')
    if voting_data.get('is_active'):
        keyboard.add('🗳️ Модель недели')
    if user_id in ADMIN_IDS:
        keyboard.add('👑 Админ-панель')

    caption = ("👋 Добро пожаловать в 'Мой Магазин 🔞'\n\n"
               "Здесь вы можете приобрести товары за Telegram Stars ⭐\n"
               "И оставаться анонимным 🥷\n\n"
               "💡 Как это работает:\n"
               "1. Выберите товар в каталоге\n"
               "2. Оплатите Stars\n"
               "3. Получите товар мгновенно!\n"
               "Удачных покупок!\n\n"
               "⚙️ Сейчас магазин находится в бета тестировании ⚙️")

    if welcome_banner:
        bot.send_photo(message.chat.id, welcome_banner, caption=caption, reply_markup=keyboard, protect_content=True)
    else:
        bot.send_message(message.chat.id, caption, reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text in ('/help', 'ℹ️ Помощь'))
def handle_help(message):
    help_text = """
📚 Доступные команды:
/start - Главное меню
/help - Эта справка
/catalog - Просмотр каталога

🛍️ Как купить:
1. Зайдите в "Каталог"
2. Выберите товар
3. Выберите способ оплаты (Stars или очки)
4. Получите товар мгновенно!

⭐ Что такое Telegram Stars?
Это внутренняя валюта Telegram для покупок в ботах.
Вы можете получить Stars в разделе "Кошелек" в настройках Telegram.

🏆 Что такое очки?
Очки ты можешь заработать внутри магазина за выполнение заданий:
• Ежедневный вход: 20🏆
• Приглашение друга: 50🏆 (за регистрацию)
• Покупка реферала: 20🏆 бонус (ТОЛЬКО если реферал покупает за Telegram Stars)
Используй очки для покупок 2🏆 = 1⭐

💰 Купить звезды можно здесь --> @PremiumBot

👥 Реферальная система:
Приглашай друзей и получай бонусы!
За каждого приглашенного: 50🏆 (после регистрации по вашей ссылке)
+20🏆 когда реферал делает покупку ЗА TELEGRAM STARS

🗳️ Модель недели:
Каждую неделю голосуйте за лучшую модель!
Победитель получает специальный статус, а на её товары – скидка 15% на следующей неделе!

🔥 Скидки:
В разделе "Скидки" каталога собраны товары, на которые в данный момент действует скидка.

❓ Проблемы с оплатой?
Напишите администратору
    """
    bot.send_message(message.chat.id, help_text, protect_content=True)


def get_available_products_for_user(user_id):
    """Возвращает словарь товаров, которые пользователь ещё не купил."""
    user = users.get(str(user_id), {})
    purchased = user.get('purchased_products', [])
    available = {}
    for pid, prod in products.items():
        if pid not in purchased:
            available[pid] = prod
    return available

@bot.message_handler(func=lambda m: m.text in ('/catalog', '🛍️ Каталог'))
def show_catalog(message):
    user_products = get_available_products_for_user(message.from_user.id)
    if not user_products:
        bot.send_message(message.chat.id, "📦 Вы уже купили все доступные товары! Загляните позже.")
        return

    categories = set(prod['category'] for prod in user_products.values())
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(types.InlineKeyboardButton("🔥 Популярное", callback_data="category_popular"))
    keyboard.add(types.InlineKeyboardButton("👤 Модели", callback_data="category_models"))
    keyboard.add(types.InlineKeyboardButton("🔥 Скидки", callback_data="category_discounts"))

    for category in categories:
        count = sum(1 for p in user_products.values() if p['category'] == category)
        keyboard.add(types.InlineKeyboardButton(
            f"📁 {category} ({count})",
            callback_data=f"category_{category}"
        ))

    bot.send_message(message.chat.id, "📚 Категории товаров:\nВыберите категорию:", reply_markup=keyboard)

@bot.message_handler(commands=['testfile'])
def test_file_command(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "Использование: /testfile product_id")
        return
    product_id = args[1]
    if product_id not in products:
        bot.send_message(message.chat.id, "Товар не найден")
        return
    product = products[product_id]
    if not product.get('media_files'):
        bot.send_message(message.chat.id, "У товара нет медиафайлов")
        return
    media_file = product['media_files'][0]
    media_path = os.path.join(MODELS_DIR, product['model_name'], product['media_type'], media_file)
    if not os.path.exists(media_path):
        bot.send_message(message.chat.id, "Файл не найден на диске")
        return
    try:
        # Попытка расшифровать и отправить админу
        send_decrypted_media(message.chat.id, media_path, product['media_type'], protect=False)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {e}")

@bot.message_handler(func=lambda m: m.text == '🎯 Задания')
def show_tasks(message):
    user_id = str(message.from_user.id)

    if user_id not in users:
        handle_start(message)
        return

    user_data = users[user_id]

    if 'daily_login' not in tasks:
        tasks['daily_login'] = {
            'name': 'Ежедневный вход',
            'description': 'Зайдите в бота каждый день',
            'points': 20,
            'type': 'daily',
            'cooldown_hours': 24
        }

    if 'referral' not in tasks:
        tasks['referral'] = {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }

    tasks_text = "🎯 Доступные задания:\n\n"

    daily_task = tasks['daily_login']
    last_login = user_data.get('last_daily_login')

    if last_login:
        try:
            last_login_date = datetime.fromisoformat(last_login).date()
            today = datetime.now().date()
            if last_login_date == today:
                status = "✅ Выполнено сегодня"
            else:
                status = "🔄 Доступно"
        except:
            status = "🔄 Доступно"
    else:
        status = "🔄 Доступно"

    tasks_text += f"1. {daily_task['name']}\n"
    tasks_text += f"   {daily_task['description']}\n"
    tasks_text += f"   Награда: {daily_task['points']}🏆\n"
    tasks_text += f"   Статус: {status}\n\n"

    ref_task = tasks['referral']
    referral_count = count_user_referrals(user_id)

    tasks_text += f"2. {ref_task['name']}\n"
    tasks_text += f"   {ref_task['description']}\n"
    tasks_text += f"   Награда: {ref_task['points']}🏆 за каждого приглашенного\n"
    tasks_text += f"   Доп. бонус: {ref_task.get('bonus_per_purchase', 0)}🏆 за покупку реферала ЗА TELEGRAM STARS\n"
    tasks_text += f"   Приглашено: {referral_count} человек\n\n"

    ref_code = user_data.get('referral_code', 'N/A')
    ref_link = f"https://t.me/{bot.get_me().username}?start={ref_code}"

    tasks_text += f"🔗 Ваша реферальная ссылка:\n{ref_link}"

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📋 Мои очки", callback_data="show_my_points"))
    keyboard.add(types.InlineKeyboardButton("👥 Поделиться ссылкой", switch_inline_query=f"Присоединяйся! Используй мою ссылку: {ref_link}"))

    bot.send_message(message.chat.id, tasks_text, reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == '👥 Реферальная система')
def show_referral_system(message):
    user_id = str(message.from_user.id)

    if user_id not in users:
        handle_start(message)
        return

    user_data = users[user_id]
    ref_code = user_data.get('referral_code', 'N/A')
    ref_link = f"https://t.me/{bot.get_me().username}?start={ref_code}"
    referral_count = count_user_referrals(user_id)

    if 'referral' not in tasks:
        tasks['referral'] = {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }

    total_earned = referral_count * tasks['referral']['points']

    ref_text = (
        f"👥 Реферальная система\n\n"
        f"🏆 Ваша статистика:\n"
        f"• Приглашено пользователей: {referral_count}\n"
        f"• Заработано очков: {total_earned}🏆\n\n"
        f"💰 Как заработать:\n"
        f"1. Делитесь своей ссылкой\n"
        f"2. За каждого приглашенного: +{tasks['referral']['points']}🏆\n"
        f"3. +{tasks['referral'].get('bonus_per_purchase', 0)}🏆 за покупку реферала ЗА TELEGRAM STARS\n\n"
        f"🔗 Ваша ссылка:\n{ref_link}\n\n"
        f"📢 Пример сообщения:\n"
        f"Присоединяйся к нашему магазину! Используй мою ссылку: {ref_link}"
    )

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📋 Список рефералов", callback_data="show_my_referrals"))
    keyboard.add(types.InlineKeyboardButton("📢 Поделиться", switch_inline_query=f"Присоединяйся по моей ссылке! {ref_link}"))

    bot.send_message(message.chat.id, ref_text, reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == '🥷 Мой профиль')
def show_profile(message):
    user_id = str(message.from_user.id)

    if user_id in users:
        user = users[user_id]
        user_orders = [order for order in orders.values() if str(order['user_id']) == user_id]

        total_orders = len(user_orders)
        completed_orders = sum(1 for order in user_orders if order['status'] == 'completed')
        total_stars_spent = 0
        total_points_spent = 0

        for order in user_orders:
            if order['status'] in ['paid', 'completed']:
                product_id = order['product_id']
                if product_id in products:
                    if order['payment_method'] == 'stars':
                        total_stars_spent += order.get('price_paid', products[product_id]['price_stars'])
                    else:
                        total_points_spent += order.get('price_paid', products[product_id]['price_stars']) * 2

        referral_count = count_user_referrals(user_id)
        ref_code = user.get('referral_code', 'N/A')

        profile_text = (
            f"🥷 Ваш профиль\n\n"
            f"📛 Имя: {user.get('first_name', 'Не указано')}\n"
            f"🔗 Username: @{user.get('username', 'Не указан')}\n"
            f"🏆 Баланс очков: {user.get('points', 0)}🏆\n"
            f"🔥 Дней подряд: {user.get('daily_login_streak', 0)}\n\n"
            f"📋 Всего заказов: {total_orders}\n"
            f"✅ Выполнено: {completed_orders}\n"
            f"💰 Потрачено: {total_stars_spent}⭐ / {total_points_spent}🏆\n\n"
            f"👥 Рефералов: {referral_count}\n"
            f"🔗 Ваш код: {ref_code}"
        )

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("🎯 Мои задания", callback_data="show_my_tasks"))
        keyboard.add(types.InlineKeyboardButton("👥 Рефералы", callback_data="show_my_referrals"))

        bot.send_message(message.chat.id, profile_text, reply_markup=keyboard)
    else:
        bot.send_message(message.chat.id, "❌ Пользователь не найден!")



# ---------- АДМИН ПАНЕЛЬ ----------
@bot.message_handler(func=lambda m: m.text in ('/admin', '👑 Админ-панель'))
def admin_menu(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Доступ запрещен!")
        return

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('✅ Добавить товар', '❌ Удалить товар')
    keyboard.add('📊 Статистика магазина', '📈 Статистика продаж')
    keyboard.add('📊 Детальная статистика', '📈 Статистика заданий')
    keyboard.add('📢 Рассылка', '🗳️ Управление голосованием')
    keyboard.add('📸 Управление фото моделей', '📝 Описание модели')
    keyboard.add('💰 Управление скидками', '⚙️ Настройки заданий')
    keyboard.add('Закрыть админ панель')
    bot.send_message(message.chat.id, "👑 Админ панель открыта", reply_markup=keyboard)

# ---------- УПРАВЛЕНИЕ ФОТО МОДЕЛЕЙ ----------
@bot.message_handler(func=lambda m: m.text == '📸 Управление фото моделей' and m.from_user.id in ADMIN_IDS)
def admin_manage_model_previews(message):
    models = get_available_models()
    if not models:
        bot.send_message(message.chat.id, "❌ Нет доступных моделей.")
        return

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in models:
        has_photo = "✅" if get_model_preview_path(model) else "❌"
        keyboard.add(types.InlineKeyboardButton(
            f"{model} [{has_photo}]",
            callback_data=f"modelpreview_{model}"
        ))

    bot.send_message(message.chat.id, "📸 Выберите модель для управления фото:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("modelpreview_"))
def model_preview_action(call):
    model = call.data[13:]
    path = get_model_preview_path(model)
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📤 Загрузить фото", callback_data=f"uploadpreview_{model}"),
        types.InlineKeyboardButton("🗑️ Удалить фото", callback_data=f"deletepreview_{model}"),
        types.InlineKeyboardButton("◀️ Назад", callback_data="back_to_models_preview")
    )

    text = f"Модель: {model}\n"
    if path:
        text += f"✅ Фото загружено: {os.path.basename(path)}"
        with open(path, 'rb') as photo:
            bot.send_photo(call.message.chat.id, photo, caption=text, reply_markup=keyboard, protect_content=True)
    else:
        text += "❌ Фото не загружено"
        bot.send_message(call.message.chat.id, text, reply_markup=keyboard)
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("uploadpreview_"))
def upload_model_preview(call):
    model = call.data[14:]
    msg = bot.send_message(call.message.chat.id, f"📸 Отправьте фото для модели {model}:")
    bot.register_next_step_handler(msg, process_model_preview_upload, model)
    bot.delete_message(call.message.chat.id, call.message.message_id)

def process_model_preview_upload(message, model):
    if message.photo:
        file_id = message.photo[-1].file_id
        path = save_model_preview(model, file_id)
        if path:
            bot.send_message(message.chat.id, f"✅ Фото для модели {model} сохранено!")
        else:
            bot.send_message(message.chat.id, "❌ Ошибка сохранения фото.")
    else:
        bot.send_message(message.chat.id, "❌ Это не фото.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("deletepreview_"))
def delete_model_preview_cmd(call):
    model = call.data[14:]
    if delete_model_preview(model):
        bot.answer_callback_query(call.id, f"✅ Фото модели {model} удалено.")
    else:
        bot.answer_callback_query(call.id, f"❌ У модели {model} нет фото.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_models_preview")
def back_to_models_preview(call):
    admin_manage_model_previews(call.message)

# ---------- ОПИСАНИЕ МОДЕЛИ ----------
@bot.message_handler(func=lambda m: m.text == '📝 Описание модели' and m.from_user.id in ADMIN_IDS)
def admin_edit_model_description(message):
    models = get_available_models()
    if not models:
        bot.send_message(message.chat.id, "❌ Нет доступных моделей.")
        return

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in models:
        has_desc = "✅" if get_model_description(model) else "❌"
        keyboard.add(types.InlineKeyboardButton(
            f"{model} [{has_desc}]",
            callback_data=f"editdesc_{model}"
        ))

    bot.send_message(message.chat.id, "📝 Выберите модель для редактирования описания:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editdesc_"))
def edit_model_description_cb(call):
    model = call.data[9:]
    current = get_model_description(model)
    msg = bot.send_message(
        call.message.chat.id,
        f"Текущее описание модели {model}:\n{current or 'отсутствует'}\n\n"
        f"Введите новое описание (или /skip чтобы пропустить):"
    )
    bot.register_next_step_handler(msg, process_model_description, model)
    bot.delete_message(call.message.chat.id, call.message.message_id)

def process_model_description(message, model):
    if message.text == '/skip':
        bot.send_message(message.chat.id, "❌ Описание не изменено.")
        return
    description = message.text.strip()
    set_model_description(model, description)
    bot.send_message(message.chat.id, f"✅ Описание для модели {model} сохранено!")

# ---------- УПРАВЛЕНИЕ СКИДКАМИ ----------
@bot.message_handler(func=lambda m: m.text == '💰 Управление скидками' and m.from_user.id in ADMIN_IDS)
def admin_discounts_menu(message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('🏆 Установить скидку на модель', '❌ Убрать скидку с модели')
    keyboard.add('« Назад в админ-панель')
    bot.send_message(message.chat.id, "💰 Управление скидками", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == '🏆 Установить скидку на модель' and m.from_user.id in ADMIN_IDS)
def admin_set_discount(message):
    models = get_available_models()
    if not models:
        bot.send_message(message.chat.id, "❌ Нет моделей.")
        return
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in models:
        keyboard.add(types.InlineKeyboardButton(model, callback_data=f"setdiscount_{model}"))
    bot.send_message(message.chat.id, "Выберите модель для установки скидки:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setdiscount_"))
def set_discount_on_model(call):
    model = call.data[12:]
    msg = bot.send_message(call.message.chat.id, f"Введите размер скидки для модели {model} (в %, только число):")
    bot.register_next_step_handler(msg, process_discount_value, model)
    bot.delete_message(call.message.chat.id, call.message.message_id)

def process_discount_value(message, model):
    try:
        discount = int(message.text.strip())
        if discount < 0 or discount > 100:
            bot.send_message(message.chat.id, "❌ Скидка должна быть от 0 до 100.")
            return
        if 'manual_discounts' not in voting_data:
            voting_data['manual_discounts'] = {}
        voting_data['manual_discounts'][model] = discount
        save_voting(voting_data)
        bot.send_message(message.chat.id, f"✅ Для модели {model} установлена скидка {discount}%.")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите целое число.")

@bot.message_handler(func=lambda m: m.text == '❌ Убрать скидку с модели' and m.from_user.id in ADMIN_IDS)
def admin_remove_discount(message):
    manual = voting_data.get('manual_discounts', {})
    if not manual:
        bot.send_message(message.chat.id, "❌ Нет активных ручных скидок.")
        return
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model, disc in manual.items():
        keyboard.add(types.InlineKeyboardButton(f"{model} - {disc}%", callback_data=f"remdiscount_{model}"))
    bot.send_message(message.chat.id, "Выберите модель для удаления скидки:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("remdiscount_"))
def remove_discount(call):
    model = call.data[12:]
    if 'manual_discounts' in voting_data and model in voting_data['manual_discounts']:
        del voting_data['manual_discounts'][model]
        save_voting(voting_data)
        bot.answer_callback_query(call.id, f"✅ Скидка для {model} удалена.")
    else:
        bot.answer_callback_query(call.id, "❌ Скидка не найдена.")



# ---------- НАСТРОЙКИ ЗАДАНИЙ ----------
@bot.message_handler(func=lambda m: m.text == '⚙️ Настройки заданий' and m.from_user.id in ADMIN_IDS)
def admin_tasks_settings(message):
    text = "⚙️ Текущие настройки заданий:\n\n"
    for task_id, task in tasks.items():
        text += f"**{task['name']}**\n"
        text += f"  ID: {task_id}\n"
        text += f"  Очки: {task['points']}\n"
        if 'bonus_per_purchase' in task:
            text += f"  Бонус за покупку: {task['bonus_per_purchase']}\n"
        text += "\n"
    text += "Выберите задание для редактирования:"

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(types.InlineKeyboardButton("Ежедневный вход", callback_data="edit_task_daily_login"))
    keyboard.add(types.InlineKeyboardButton("Реферальная система", callback_data="edit_task_referral"))
    keyboard.add(types.InlineKeyboardButton("« Назад", callback_data="back_to_admin_tasks"))

    bot.send_message(message.chat.id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_task_'))
def edit_task_callback(call):
    task_id = call.data.replace('edit_task_', '')
    if task_id not in tasks:
        bot.answer_callback_query(call.id, "Задание не найдено")
        return
    task = tasks[task_id]
    msg = bot.send_message(call.message.chat.id,
                          f"Редактирование: {task['name']}\n"
                          f"Текущие очки: {task['points']}\n"
                          f"Введите новое количество очков:")
    bot.register_next_step_handler(msg, process_task_points_edit, task_id)
    bot.delete_message(call.message.chat.id, call.message.message_id)

def process_task_points_edit(message, task_id):
    try:
        points = int(message.text)
        tasks[task_id]['points'] = points
        save_data(TASKS_FILE, tasks)
        bot.send_message(message.chat.id, f"✅ Очки за задание обновлены: {points}")
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите число.")

# ---------- АДМИН: УПРАВЛЕНИЕ ГОЛОСОВАНИЕМ ----------
@bot.message_handler(func=lambda m: m.text == '🗳️ Управление голосованием' and m.from_user.id in ADMIN_IDS)
def admin_voting_menu(message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('🔄 Начать новое голосование')
    keyboard.add('➕ Добавить модель в список', '➖ Удалить модель из списка')
    keyboard.add('🏆 Завершить голосование')
    keyboard.add('📊 Текущий рейтинг')
    keyboard.add('« Назад в админ-панель')
    bot.send_message(message.chat.id, "🗳️ Управление голосованием", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == '« Назад в админ-панель' and m.from_user.id in ADMIN_IDS)
def back_to_admin(message):
    admin_menu(message)

@bot.message_handler(func=lambda m: m.text == '🔄 Начать новое голосование' and m.from_user.id in ADMIN_IDS)
def admin_start_voting(message):
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    start_new_voting_period(monday)
    bot.send_message(message.chat.id, "✅ Новое голосование начато! Все модели добавлены как кандидаты.")

@bot.message_handler(func=lambda m: m.text == '➕ Добавить модель в список' and m.from_user.id in ADMIN_IDS)
def admin_add_candidate(message):
    available = get_available_models()
    if not available:
        bot.send_message(message.chat.id, "❌ Нет доступных моделей в папке 'models'.")
        return

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in available:
        if model not in voting_data['candidates']:
            keyboard.add(types.InlineKeyboardButton(model, callback_data=f"admin_addcand_{model}"))
    if not keyboard.keyboard:
        bot.send_message(message.chat.id, "✅ Все существующие модели уже в списке.")
        return
    bot.send_message(message.chat.id, "Выберите модель для добавления:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_addcand_"))
def admin_add_candidate_cb(call):
    model = call.data.replace('admin_addcand_', '')
    if model not in voting_data['candidates']:
        voting_data['candidates'][model] = 0
        save_voting(voting_data)
        bot.answer_callback_query(call.id, f"✅ Модель {model} добавлена в голосование.")
    else:
        bot.answer_callback_query(call.id, "⚠️ Модель уже в списке.")

@bot.message_handler(func=lambda m: m.text == '➖ Удалить модель из списка' and m.from_user.id in ADMIN_IDS)
def admin_remove_candidate(message):
    if not voting_data['candidates']:
        bot.send_message(message.chat.id, "📭 Список кандидатов пуст.")
        return
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in voting_data['candidates'].keys():
        keyboard.add(types.InlineKeyboardButton(model, callback_data=f"admin_remcand_{model}"))
    bot.send_message(message.chat.id, "Выберите модель для удаления:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_remcand_"))
def admin_remove_candidate_cb(call):
    model = call.data.replace('admin_remcand_', '')
    if model in voting_data['candidates']:
        del voting_data['candidates'][model]
        save_voting(voting_data)
        bot.answer_callback_query(call.id, f"✅ Модель {model} удалена из голосования.")
    else:
        bot.answer_callback_query(call.id, "⚠️ Модель не найдена.")

@bot.message_handler(func=lambda m: m.text == '🏆 Завершить голосование' and m.from_user.id in ADMIN_IDS)
def admin_finish_voting(message):
    if not voting_data['is_active']:
        bot.send_message(message.chat.id, "❌ Нет активного голосования.")
        return
    winner = finish_voting()
    bot.send_message(message.chat.id, f"🏆 Голосование завершено! Победитель: {winner}")

@bot.message_handler(func=lambda m: m.text == '📊 Текущий рейтинг' and m.from_user.id in ADMIN_IDS)
def admin_show_rating(message):
    if not voting_data['candidates']:
        bot.send_message(message.chat.id, "📭 Список кандидатов пуст.")
        return
    sorted_cands = sorted(voting_data['candidates'].items(), key=lambda x: x[1], reverse=True)
    text = "📊 Текущий рейтинг голосования\n\n"
    for i, (model, votes) in enumerate(sorted_cands, 1):
        text += f"{i}. {model} – {votes} голосов\n"
    text += f"\n✅ Проголосовало: {len(voting_data['voted_users'])} пользователей"
    bot.send_message(message.chat.id, text)

# ---------- ПОЛЬЗОВАТЕЛЬСКОЕ ГОЛОСОВАНИЕ ----------
@bot.message_handler(func=lambda m: m.text == '🗳️ Модель недели')
def show_voting_menu(message):
    if not voting_data.get('is_active'):
        bot.send_message(message.chat.id, "⏳ Голосование ещё не начато. Загляните на следующей неделе!")
        return

    candidates = voting_data.get('candidates', {})
    if not candidates:
        bot.send_message(message.chat.id, "📭 Список моделей пуст. Администратор скоро добавит кандидатов.")
        return

    user_id = message.from_user.id
    already_voted = user_id in voting_data.get('voted_users', [])

    text = "🗳️ Голосование «Модель недели»\n\n"
    text += "Проголосуйте за лучшую модель!\n\n"
    sorted_cands = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    for idx, (model, votes) in enumerate(sorted_cands, 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "🔹"
        text += f"{medal} {model} – {votes} голосов\n"

    text += f"\n📅 Неделя: {voting_data['week_start']}\n"

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    if not already_voted:
        keyboard.add(types.InlineKeyboardButton("🗳️ Проголосовать", callback_data="voting_show_candidates"))
    else:
        text += "\n✅ Вы уже проголосовали на этой неделе."

    bot.send_message(message.chat.id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "voting_show_candidates")
def voting_show_candidates(call):
    if not voting_data['is_active']:
        bot.answer_callback_query(call.id, "Голосование не активно")
        return

    if call.from_user.id in voting_data['voted_users']:
        bot.answer_callback_query(call.id, "Вы уже голосовали на этой неделе!", show_alert=True)
        return

    candidates = voting_data['candidates']
    if not candidates:
        bot.answer_callback_query(call.id, "Нет доступных моделей")
        return

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for model in candidates.keys():
        keyboard.add(types.InlineKeyboardButton(model, callback_data=f"vote_{model}"))

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="Выберите модель, которой отдаёте свой голос:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("vote_"))
def process_vote(call):
    if not voting_data['is_active']:
        bot.answer_callback_query(call.id, "Голосование не активно")
        return

    user_id = call.from_user.id
    if user_id in voting_data['voted_users']:
        bot.answer_callback_query(call.id, "Вы уже голосовали!", show_alert=True)
        return

    model = call.data[5:]
    if model not in voting_data['candidates']:
        bot.answer_callback_query(call.id, "Модель не найдена")
        return

    voting_data['candidates'][model] += 1
    voting_data['voted_users'].append(user_id)
    save_voting(voting_data)

    bot.answer_callback_query(call.id, f"✅ Ваш голос засчитан за модель «{model}»!")
    show_voting_menu(call.message)



# ---------- АДМИН: ДОБАВЛЕНИЕ ТОВАРА ----------
@bot.message_handler(func=lambda message: message.text == '✅ Добавить товар' and message.from_user.id in ADMIN_IDS)
def start_add_product(message):
    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)

    existing_models = get_available_models()

    if existing_models:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for model in existing_models:
            keyboard.add(f"Модель: {model}")
        keyboard.add("➕ Создать новую модель")
        keyboard.add("❌ Отмена")

        msg = bot.send_message(message.chat.id, "📁 Выберите существующую модель или создайте новую:", reply_markup=keyboard)
        bot.register_next_step_handler(msg, handle_model_selection)
    else:
        msg = bot.send_message(message.chat.id, "📁 Введите имя новой модели:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, create_new_model)

def handle_model_selection(message):
    if message.text == "➕ Создать новую модель":
        msg = bot.send_message(message.chat.id, "📁 Введите имя новой модели:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, create_new_model)
    elif message.text == "❌ Отмена":
        admin_menu(message)
    elif message.text.startswith("Модель: "):
        model_name = message.text.replace("Модель: ", "").strip()
        msg = bot.send_message(message.chat.id, f"📝 Введите название товара для модели '{model_name}':", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, add_product_description, model_name)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")
        admin_menu(message)

def create_new_model(message):
    model_name = message.text.strip()
    model_path = os.path.join(MODELS_DIR, model_name)

    if os.path.isdir(model_path):
        bot.send_message(message.chat.id, f"⚠️ Модель «{model_name}» уже существует.")
    else:
        os.makedirs(model_path, exist_ok=True)
        os.makedirs(os.path.join(model_path, "photo"), exist_ok=True)
        os.makedirs(os.path.join(model_path, "video"), exist_ok=True)
        os.makedirs(os.path.join(model_path, "covers"), exist_ok=True)
        bot.send_message(message.chat.id, f"✅ Создана структура для модели «{model_name}»")
        if voting_data.get('is_active') and model_name not in voting_data['candidates']:
            voting_data['candidates'][model_name] = 0
            save_voting(voting_data)

    msg = bot.send_message(message.chat.id, f"📝 Введите название товара для модели '{model_name}':", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, add_product_description, model_name)

def add_product_description(message, model_name):
    if not message.text:
        bot.send_message(message.chat.id, "❌ Название товара не может быть пустым!")
        return admin_menu(message)

    product_name = message.text.strip()
    msg = bot.send_message(message.chat.id, "📝 Введите описание товара:")
    bot.register_next_step_handler(msg, add_product_price, model_name, product_name)

def add_product_price(message, model_name, product_name):
    product_description = message.text.strip()
    msg = bot.send_message(message.chat.id, "💰 Введите цену в Stars (только число):")
    bot.register_next_step_handler(msg, add_product_category, model_name, product_name, product_description)

def add_product_category(message, model_name, product_name, product_description):
    try:
        price = int(message.text)

        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('📦 Медиа товар', '🔗 Доступ в канал')
        keyboard.add('❌ Отмена')

        msg = bot.send_message(message.chat.id, "🏷️ Выберите тип товара:", reply_markup=keyboard)
        bot.register_next_step_handler(msg, select_product_type, model_name, product_name, product_description, price)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверная цена! Используйте только цифры.")
        return

def select_product_type(message, model_name, product_name, product_description, price):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '📦 Медиа товар':
        msg = bot.send_message(message.chat.id, "🏷️ Введите категорию товара:")
        bot.register_next_step_handler(msg, add_product_cover, model_name, product_name, product_description, price, 'media')
    elif message.text == '🔗 Доступ в канал':
        msg = bot.send_message(message.chat.id, "🔗 Введите ID канала (например: -1001234567890):")
        bot.register_next_step_handler(msg, add_channel_info, model_name, product_name, product_description, price)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")

def add_channel_info(message, model_name, product_name, product_description, price):
    channel_id = message.text.strip()
    msg = bot.send_message(
        message.chat.id,
        "🔗 Введите пригласительную ссылку на канал (обязательно):\n\n"
        "ℹ️ Пользователи будут получать доступ через эту ссылку после покупки.\n"
        "ℹ️ Пример: https://t.me/joinchat/XXXXXXXXXXXXX"
    )
    bot.register_next_step_handler(
        msg,
        add_channel_welcome,
        model_name, product_name, product_description, price, channel_id
    )

def add_channel_welcome(message, model_name, product_name, product_description, price, channel_id):
    channel_invite_link = message.text.strip()
    msg = bot.send_message(
        message.chat.id,
        "📝 Введите приветственное сообщение для нового участника (или 'нет' для стандартного):\n\n"
        "ℹ️ Это сообщение будет отправлено пользователю после покупки вместе со ссылкой на канал."
    )
    bot.register_next_step_handler(
        msg,
        finish_channel_product,
        model_name, product_name, product_description, price, channel_id, channel_invite_link
    )

def finish_channel_product(message, model_name, product_name, product_description, price, channel_id, channel_invite_link):
    welcome_message = None if message.text.lower() == 'нет' else message.text.strip()
    product_id = generate_product_id()

    product = Product(
        product_id=product_id,
        name=product_name,
        description=product_description,
        price_stars=price,
        category='Доступ в канал',
        model_name=model_name,
        channel_id=channel_id,
        channel_invite_link=channel_invite_link,
        welcome_message=welcome_message
    )

    products[product_id] = product.to_dict()
    save_data(PRODUCTS_FILE, products)

    success_message = (
        f"✅ Товар с доступом в канал успешно добавлен!\n\n"
        f"📋 ID: {product_id}\n"
        f"📦 Название: {product_name}\n"
        f"💰 Цена: {price} Stars\n"
        f"🔗 Канал ID: {channel_id}\n"
        f"📎 Пригласительная ссылка: {'✅' if channel_invite_link else '❌'}\n"
        f"👋 Приветствие: {'✅' if welcome_message else '❌'}\n\n"
        f"⚡ Особенности системы:\n"
        f"• Пользователи получат одноразовые ссылки для активации\n"
        f"• После активации им будет отправлена пригласительная ссылка\n"
        f"• Отслеживание всех активаций"
    )

    bot.send_message(message.chat.id, success_message)
    admin_menu(bot.send_message(message.chat.id, "Возвращаемся в админ-панель..."))



def add_product_cover(message, model_name, product_name, product_description, price, product_type):
    category = message.text.strip()
    product_id = generate_product_id()

    user_data = {
        'model_name': model_name,
        'product_name': product_name,
        'product_description': product_description,
        'price': price,
        'category': category,
        'product_id': product_id,
        'cover_file': None,
        'product_type': product_type,
        'blur_photos': False,
        'auto_delete': False,
        'auto_delete_minutes': 15
    }

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add('📸 Загрузить обложку', '⏭️ Пропустить обложку')
    keyboard.add('❌ Отмена')

    msg = bot.send_message(message.chat.id, "🖼️ Хотите загрузить обложку для товара?", reply_markup=keyboard)
    bot.register_next_step_handler(msg, handle_cover_selection, user_data)

def handle_cover_selection(message, user_data):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '📸 Загрузить обложку':
        msg = bot.send_message(message.chat.id, "🖼️ Отправьте фото для обложки товара:", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_cover_upload, user_data)
    elif message.text == '⏭️ Пропустить обложку':
        ask_blur_option(user_data, message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")

def process_cover_upload(message, user_data):
    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id

        saved_filename = save_file_from_telegram(
            file_id,
            'photo',
            user_data['model_name'],
            user_data['product_id'],
            'covers'
        )

        if saved_filename:
            user_data['cover_file'] = saved_filename
            bot.send_message(message.chat.id, "✅ Обложка сохранена!")

    ask_blur_option(user_data, message.chat.id)

def ask_blur_option(user_data, chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add('✅ Да, размыть фото', '❌ Нет, не размывать')
    keyboard.add('❌ Отмена')

    msg = bot.send_message(
        chat_id,
        "🔒 Размыть фотографии товара для защиты контента?\n\n"
        "⚠️ Фото будут физически размыты (блюр эффект) перед отправкой покупателям.",
        reply_markup=keyboard
    )
    bot.register_next_step_handler(msg, handle_blur_selection, user_data)

def handle_blur_selection(message, user_data):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '✅ Да, размыть фото':
        user_data['blur_photos'] = True
        bot.send_message(message.chat.id, "✅ Фото будут размыты перед отправкой покупателям!")
    elif message.text == '❌ Нет, не размывать':
        user_data['blur_photos'] = False
        bot.send_message(message.chat.id, "✅ Фото будут отправлены без размытия.")
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")
        return ask_blur_option(user_data, message.chat.id)

    ask_auto_delete_option(user_data, message.chat.id)

def ask_auto_delete_option(user_data, chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add('✅ Да, включить автоудаление', '❌ Нет, не включать')
    keyboard.add('❌ Отмена')

    msg = bot.send_message(
        chat_id,
        "⏰ Включить автоудаление медиафайлов через 15 минут?\n\n"
        "⚠️ Если включено, все медиафайлы будут автоматически удалены из чата покупателя через 15 минут после отправки.",
        reply_markup=keyboard
    )
    bot.register_next_step_handler(msg, handle_auto_delete_selection, user_data)

def handle_auto_delete_selection(message, user_data):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '✅ Да, включить автоудаление':
        user_data['auto_delete'] = True
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        keyboard.add('15 минут', '30 минут', '60 минут')
        keyboard.add('❌ Отмена')

        msg = bot.send_message(
            message.chat.id,
            "⏱️ Выберите время до автоудаления:",
            reply_markup=keyboard
        )
        bot.register_next_step_handler(msg, handle_delete_time_selection, user_data)
    elif message.text == '❌ Нет, не включать':
        user_data['auto_delete'] = False
        bot.send_message(message.chat.id, "❌ Автоудаление отключено.")
        select_media_type_after_options(user_data, message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")
        return ask_auto_delete_option(user_data, message.chat.id)

def handle_delete_time_selection(message, user_data):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '15 минут':
        user_data['auto_delete_minutes'] = 15
    elif message.text == '30 минут':
        user_data['auto_delete_minutes'] = 30
    elif message.text == '60 минут':
        user_data['auto_delete_minutes'] = 60
    else:
        try:
            minutes = int(message.text)
            if 1 <= minutes <= 1440:
                user_data['auto_delete_minutes'] = minutes
            else:
                bot.send_message(message.chat.id, "❌ Введите число от 1 до 1440 минут!")
                return handle_delete_time_selection(message, user_data)
        except:
            bot.send_message(message.chat.id, "❌ Неверный выбор!")
            return handle_delete_time_selection(message, user_data)

    bot.send_message(
        message.chat.id,
        f"✅ Автоудаление включено! Медиафайлы будут удалены через {user_data['auto_delete_minutes']} минут."
    )
    select_media_type_after_options(user_data, message.chat.id)

def select_media_type_after_options(user_data, chat_id):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add('📸 Фото', '🎥 Видео')
    keyboard.add('❌ Отмена')

    settings_text = f"📁 Выберите тип контента для товара:\n\n"
    settings_text += f"🔒 Размытие фото: {'✅' if user_data.get('blur_photos', False) else '❌'}\n"
    settings_text += f"⏰ Автоудаление: {'✅ (' + str(user_data.get('auto_delete_minutes', 15)) + ' мин)' if user_data.get('auto_delete', False) else '❌'}"

    msg = bot.send_message(chat_id, settings_text, reply_markup=keyboard)
    bot.register_next_step_handler(msg, handle_media_type_selection, user_data)

def handle_media_type_selection(message, user_data):
    if message.text == '❌ Отмена':
        admin_menu(message)
        return

    if message.text == '📸 Фото':
        user_data['media_type'] = 'photo'
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('✅ Готово')
        keyboard.add('❌ Отмена')

        settings_info = ""
        if user_data.get('blur_photos', False):
            settings_info += "🔒 Фото будут размыты\n"
        if user_data.get('auto_delete', False):
            settings_info += f"⏰ Автоудаление через {user_data.get('auto_delete_minutes', 15)} минут\n"

        msg = bot.send_message(
            message.chat.id,
            f"📸 Отправьте фото для товара (можно несколько):\n\n"
            f"{settings_info}"
            f"После отправки всех фото нажмите '✅ Готово'",
            reply_markup=keyboard
        )
        bot.register_next_step_handler(msg, handle_photo_upload, user_data)
    elif message.text == '🎥 Видео':
        user_data['media_type'] = 'video'
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('✅ Готово')
        keyboard.add('❌ Отмена')

        settings_info = ""
        if user_data.get('auto_delete', False):
            settings_info += f"⏰ Автоудаление через {user_data.get('auto_delete_minutes', 15)} минут\n"

        msg = bot.send_message(
            message.chat.id,
            f"🎥 Отправьте видео для товара (можно несколько):\n\n"
            f"{settings_info}"
            f"После отправки всех видео нажмите '✅ Готово'",
            reply_markup=keyboard
        )
        bot.register_next_step_handler(msg, handle_video_upload, user_data)
    else:
        bot.send_message(message.chat.id, "❌ Неверный выбор!")



def handle_photo_upload(message, user_data):
    if 'media_files' not in user_data:
        user_data['media_files'] = []

    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id

        saved_filename = save_file_from_telegram(
            file_id,
            'photo',
            user_data['model_name'],
            user_data['product_id']
        )

        if saved_filename:
            user_data['media_files'].append(saved_filename)

            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.add('✅ Готово')
            keyboard.add('❌ Отмена')

            settings_info = ""
            if user_data.get('blur_photos', False):
                settings_info += "🔒 Размытие: ✅\n"
            if user_data.get('auto_delete', False):
                settings_info += f"⏰ Автоудаление: ✅ ({user_data.get('auto_delete_minutes', 15)} мин)\n"

            bot.send_message(
                message.chat.id,
                f"✅ Фото сохранено! Загружено фото: {len(user_data['media_files'])}\n"
                f"{settings_info}"
                f"Отправьте еще фото или нажмите '✅ Готово'",
                reply_markup=keyboard
            )

            bot.register_next_step_handler(message, handle_photo_upload, user_data)
        else:
            bot.send_message(message.chat.id, "❌ Ошибка сохранения фото!")
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.add('✅ Готово')
            keyboard.add('❌ Отмена')
            bot.send_message(message.chat.id, "Попробуйте отправить фото еще раз или нажмите '✅ Готово'", reply_markup=keyboard)
            bot.register_next_step_handler(message, handle_photo_upload, user_data)

    elif message.text == '✅ Готово':
        if not user_data['media_files']:
            bot.send_message(message.chat.id, "❌ Нет загруженных фото!")
            return admin_menu(message)

        save_product_final(user_data, message.chat.id)

    elif message.text == '❌ Отмена':
        admin_menu(message)

    else:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('✅ Готово')
        keyboard.add('❌ Отмена')
        bot.send_message(message.chat.id, "Пожалуйста, отправьте фото или нажмите '✅ Готово'", reply_markup=keyboard)
        bot.register_next_step_handler(message, handle_photo_upload, user_data)

def handle_video_upload(message, user_data):
    if 'media_files' not in user_data:
        user_data['media_files'] = []

    if message.video:
        video = message.video
        file_id = video.file_id

        saved_filename = save_file_from_telegram(
            file_id,
            'video',
            user_data['model_name'],
            user_data['product_id']
        )

        if saved_filename:
            user_data['media_files'].append(saved_filename)

            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.add('✅ Готово')
            keyboard.add('❌ Отмена')

            settings_info = ""
            if user_data.get('auto_delete', False):
                settings_info += f"⏰ Автоудаление: ✅ ({user_data.get('auto_delete_minutes', 15)} мин)\n"

            bot.send_message(
                message.chat.id,
                f"✅ Видео сохранено! Загружено видео: {len(user_data['media_files'])}\n"
                f"{settings_info}"
                f"Отправьте еще видео или нажмите '✅ Готово'",
                reply_markup=keyboard
            )

            bot.register_next_step_handler(message, handle_video_upload, user_data)
        else:
            bot.send_message(message.chat.id, "❌ Ошибка сохранения видео!")
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.add('✅ Готово')
            keyboard.add('❌ Отмена')
            bot.send_message(message.chat.id, "Попробуйте отправить видео еще раз или нажмите '✅ Готово'", reply_markup=keyboard)
            bot.register_next_step_handler(message, handle_video_upload, user_data)

    elif message.text == '✅ Готово':
        if not user_data['media_files']:
            bot.send_message(message.chat.id, "❌ Нет загруженных видео!")
            return admin_menu(message)

        save_product_final(user_data, message.chat.id)

    elif message.text == '❌ Отмена':
        admin_menu(message)

    else:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('✅ Готово')
        keyboard.add('❌ Отмена')
        bot.send_message(message.chat.id, "Пожалуйста, отправьте видео или нажмите '✅ Готово'", reply_markup=keyboard)
        bot.register_next_step_handler(message, handle_video_upload, user_data)

def save_product_final(user_data, chat_id):
    product = Product(
        product_id=user_data['product_id'],
        name=user_data['product_name'],
        description=user_data['product_description'],
        price_stars=user_data['price'],
        category=user_data['category'],
        model_name=user_data['model_name'],
        media_files=user_data['media_files'],
        media_type=user_data['media_type'],
        cover_file=user_data['cover_file'],
        purchase_count=0,
        blur_photos=user_data.get('blur_photos', False),
        auto_delete=user_data.get('auto_delete', False),
        auto_delete_minutes=user_data.get('auto_delete_minutes', 15)
    )

    products[user_data['product_id']] = product.to_dict()
    save_data(PRODUCTS_FILE, products)

    success_message = (
        f"✅ Товар успешно добавлен!\n\n"
        f"📋 ID: {user_data['product_id']}\n"
        f"📦 Название: {user_data['product_name']}\n"
        f"📝 Описание: {user_data['product_description']}\n"
        f"💰 Цена: {user_data['price']} Stars\n"
        f"🏷️ Категория: {user_data['category']}\n"
        f"👤 Модель: {user_data['model_name']}\n"
        f"📁 Тип: {user_data['media_type']}\n"
        f"🖼️ Обложка: {'✅' if user_data['cover_file'] else '❌'}\n"
        f"🔒 Размытие фото: {'✅' if user_data.get('blur_photos', False) else '❌'}\n"
        f"⏰ Автоудаление: {'✅ (' + str(user_data.get('auto_delete_minutes', 15)) + ' мин)' if user_data.get('auto_delete', False) else '❌'}\n"
        f"📎 Файлов: {len(user_data['media_files'])}"
    )

    bot.send_message(chat_id, success_message)
    admin_menu(bot.send_message(chat_id, "Возвращаемся в админ-панель..."))

# ---------- АДМИН: УДАЛЕНИЕ ТОВАРА ----------
@bot.message_handler(func=lambda message: message.text == '❌ Удалить товар' and message.from_user.id in ADMIN_IDS)
def delete_product_start(message):
    if not products:
        bot.send_message(message.chat.id, "📦 Каталог пуст, удалять нечего!")
        return

    keyboard = types.InlineKeyboardMarkup()
    for product_id, product in products.items():
        button_text = f"{product['name']} - {product['price_stars']}⭐"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."
        keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"delete:{product_id}"))

    bot.send_message(message.chat.id, "❌ Выберите товар для удаления:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete:'))
def delete_product_confirm(call):
    product_id = call.data.split(':', 1)[1]

    if product_id in products:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{product_id}"),
            types.InlineKeyboardButton("❌ Нет, отменить", callback_data="cancel_delete")
        )

        product = products[product_id]
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"❓ Вы уверены, что хотите удалить товар?\n\n📦 {product['name']}\n💰 {product['price_stars']} Stars\n🏷️ {product['category']}",
            reply_markup=keyboard
        )
    else:
        bot.answer_callback_query(call.id, "❌ Товар не найден!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_delete:'))
def delete_product_final(call):
    product_id = call.data.split(':', 1)[1]

    if product_id in products:
        deleted_product = products.pop(product_id)
        save_data(PRODUCTS_FILE, products)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Товар удален:\n{deleted_product['name']}"
        )
    else:
        bot.answer_callback_query(call.id, "❌ Товар не найден!")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_delete')
def cancel_delete(call):
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="❌ Удаление отменено."
    )


# ---------- АДМИН: СТАТИСТИКА ----------
@bot.message_handler(func=lambda message: message.text == '📊 Статистика магазина' and message.from_user.id in ADMIN_IDS)
def show_statistics(message):
    total_users = len(users)
    total_products = len(products)
    total_orders = len(orders)

    pending_orders = sum(1 for order in orders.values() if order['status'] == 'pending')
    completed_orders = sum(1 for order in orders.values() if order['status'] == 'completed')
    paid_orders = sum(1 for order in orders.values() if order['status'] == 'paid')

    model_count = len(get_available_models())

    total_purchases = sum(product.get('purchase_count', 0) for product in products.values())

    total_stars_spent = 0
    total_points_spent = 0
    total_stars_revenue = 0

    for order in orders.values():
        if order['status'] in ['paid', 'completed']:
            product = products.get(order['product_id'])
            if product:
                price_paid = order.get('price_paid', product['price_stars'])
                if order['payment_method'] == 'stars':
                    total_stars_spent += price_paid
                    total_stars_revenue += price_paid
                else:
                    total_points_spent += price_paid * 2

    channel_products = sum(1 for product in products.values() if product.get('is_channel_access', False))
    blurred_products = sum(1 for product in products.values() if product.get('blur_photos', False))
    auto_delete_products = sum(1 for product in products.values() if product.get('auto_delete', False))

    stats_text = (
        f"📊 Статистика магазина\n\n"
        f"👥 Пользователи: {total_users}\n"
        f"📦 Товары: {total_products}\n"
        f"  • Медиа: {total_products - channel_products}\n"
        f"  • Доступы в каналы: {channel_products}\n"
        f"  • Размытые фото: {blurred_products}\n"
        f"  • С автоудалением: {auto_delete_products}\n"
        f"👤 Модели: {model_count}\n"
        f"📋 Всего заказов: {total_orders}\n"
        f"⏳ Ожидают оплаты: {pending_orders}\n"
        f"✅ Оплачено: {paid_orders}\n"
        f"🎉 Выполнено: {completed_orders}\n"
        f"🛒 Всего покупок: {total_purchases}\n\n"
        f"💰 Потрачено пользователями:\n"
        f"   ⭐ Stars: {total_stars_spent}\n"
        f"   🏆 Очки:  {total_points_spent}\n\n"
        f"💰 Общая выручка (звёзды): {total_stars_revenue}⭐"
    )

    bot.send_message(message.chat.id, stats_text)

@bot.message_handler(func=lambda message: message.text == '📈 Статистика продаж' and message.from_user.id in ADMIN_IDS)
def sales_statistics_menu(message):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📆 Неделя", callback_data="stats_week"),
        types.InlineKeyboardButton("📅 Месяц", callback_data="stats_month"),
        types.InlineKeyboardButton("📊 Год", callback_data="stats_year"),
        types.InlineKeyboardButton("⏳ Всё время", callback_data="stats_all")
    )

    bot.send_message(
        message.chat.id,
        "📊 Статистика продаж\n\n"
        "Выберите период для просмотра статистики:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('stats_'))
def handle_stats_period(call):
    period = call.data.replace('stats_', '')
    bot.answer_callback_query(call.id, f"📊 Собираем статистику за {period}...")
    stats = get_statistics_by_period(period)
    stats_message = format_statistics_message(stats)

    if len(stats_message) > 4000:
        parts = []
        while len(stats_message) > 4000:
            split_pos = stats_message[:4000].rfind('\n')
            if split_pos == -1:
                split_pos = 4000
            parts.append(stats_message[:split_pos])
            stats_message = stats_message[split_pos:]
        parts.append(stats_message)

        for i, part in enumerate(parts, 1):
            if i == 1:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=part + f"\n\n📄 Часть {i}/{len(parts)}"
                )
            else:
                bot.send_message(
                    call.message.chat.id,
                    part + f"\n\n📄 Часть {i}/{len(parts)}"
                )
    else:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=stats_message
        )

@bot.message_handler(func=lambda message: message.text == '📊 Детальная статистика' and message.from_user.id in ADMIN_IDS)
def show_detailed_stats(message):
    stats = get_detailed_models_stats()
    if not stats:
        bot.send_message(message.chat.id, "📭 Нет данных для отображения.")
        return

    text = "📊 Детальная статистика по моделям\n\n"
    for model, data in stats.items():
        text += f"👤 Модель: {model}\n"
        text += f"   📦 Продаж: {data['total_sales']}\n"
        text += f"   ⭐ Stars: {data['stars_earned']}\n"
        text += f"   🏆 Очки: {data['points_earned']}\n"
        text += f"   Товары:\n"
        for pid, prod in data['products'].items():
            text += f"      • {prod['name']}\n"
            text += f"         Продаж: {prod['sales']}, ⭐{prod['stars']}, 🏆{prod['points']}\n"
        text += "\n"

    if len(text) > 4000:
        for part in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            bot.send_message(message.chat.id, part)
    else:
        bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == '📈 Статистика заданий' and message.from_user.id in ADMIN_IDS)
def show_tasks_statistics(message):
    if 'daily_login' not in tasks:
        tasks['daily_login'] = {
            'name': 'Ежедневный вход',
            'description': 'Зайдите в бота каждый день',
            'points': 20,
            'type': 'daily',
            'cooldown_hours': 24
        }

    if 'referral' not in tasks:
        tasks['referral'] = {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }

    total_points_earned = sum(user.get('points', 0) for user in users.values())
    total_daily_logins = sum(user.get('daily_login_streak', 0) for user in users.values())
    total_referrals = sum(count_user_referrals(uid) for uid in users.keys())

    stats_text = (
        f"📊 Статистика заданий\n\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"🏆 Всего начислено очков: {total_points_earned}🏆\n"
        f"🔥 Сумма серий дней: {total_daily_logins}\n"
        f"👥 Всего рефералов: {total_referrals}\n\n"
        f"📈 Топ-5 по очкам:\n"
    )

    sorted_users = sorted(users.items(), key=lambda x: x[1].get('points', 0), reverse=True)[:5]
    for i, (uid, user_data) in enumerate(sorted_users, 1):
        stats_text += f"{i}. @{user_data.get('username', 'No username')}: {user_data.get('points', 0)}🏆\n"

    bot.send_message(message.chat.id, stats_text)

# ---------- АДМИН: РАССЫЛКА С МЕДИА ----------
@bot.message_handler(func=lambda message: message.text == '📢 Рассылка' and message.from_user.id in ADMIN_IDS)
def start_broadcast(message):
    msg = bot.send_message(
        message.chat.id,
        "📢 Отправьте сообщение для рассылки (можно с фото, видео, документом):\n"
        "Просто отправьте мне контент, и я разошлю его всем пользователям.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    sent_count = 0
    failed_count = 0

    content_type = None
    file_id = None
    caption = message.caption or message.text or ""

    if message.photo:
        content_type = 'photo'
        file_id = message.photo[-1].file_id
    elif message.video:
        content_type = 'video'
        file_id = message.video.file_id
    elif message.document:
        content_type = 'document'
        file_id = message.document.file_id
    else:
        content_type = 'text'

    for user_id in users.keys():
        try:
            if content_type == 'photo':
                bot.send_photo(int(user_id), file_id, caption=caption, protect_content=True)
            elif content_type == 'video':
                bot.send_video(int(user_id), file_id, caption=caption, protect_content=True)
            elif content_type == 'document':
                bot.send_document(int(user_id), file_id, caption=caption, protect_content=True)
            else:
                bot.send_message(int(user_id), caption)
            sent_count += 1
            time.sleep(0.05)
        except Exception as e:
            print(f"Ошибка отправки пользователю {user_id}: {e}")
            failed_count += 1

    bot.send_message(
        message.chat.id,
        f"✅ Рассылка завершена!\n\n"
        f"✅ Отправлено: {sent_count}\n"
        f"❌ Не отправлено: {failed_count}"
    )
    admin_menu(message)

@bot.message_handler(func=lambda message: message.text == 'Закрыть админ панель')
def close_admin(message):
    handle_start(message)


# ---------- ОБРАБОТЧИКИ КАТЕГОРИЙ И ТОВАРОВ ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('category_'))
def show_category_products(call):
    user_products = get_available_products_for_user(call.from_user.id)
    category = call.data.replace('category_', '')

    if category == 'popular':
        all_popular = get_popular_products(5)
        popular_products = [p for p in all_popular if p['id'] in user_products]
        if not popular_products:
            bot.answer_callback_query(call.id, "❌ Среди популярных нет доступных товаров!")
            return

        keyboard = types.InlineKeyboardMarkup()
        for product in popular_products:
            button_text = f"🔥 {product['name']} - {product['price_stars']}⭐ ({product.get('purchase_count', 0)}👤)"
            if len(button_text) > 50:
                button_text = button_text[:47] + "..."
            keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"view:{product['id']}"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"🔥 Самые популярные товары:\n\nТоп-5 товаров по количеству покупок",
            reply_markup=keyboard
        )

    elif category == 'models':
        models = get_models_with_products()
        filtered_models = {}
        for model_name, model_prods in models.items():
            available_prods = [p for p in model_prods if p['id'] in user_products]
            if available_prods:
                filtered_models[model_name] = available_prods
        if not filtered_models:
            bot.answer_callback_query(call.id, "❌ Нет доступных моделей!")
            return

        keyboard = types.InlineKeyboardMarkup()
        for model_name, model_products in filtered_models.items():
            product_count = len(model_products)
            total_purchases = sum(p.get('purchase_count', 0) for p in model_products)
            button_text = f"👤 {model_name} ({product_count}📦, {total_purchases}👤)"
            keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"model_{model_name}"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"👤 Все модели:\n\nВыберите модель для просмотра товаров:",
            reply_markup=keyboard
        )

    elif category == 'discounts':
        discounted = get_discounted_products()
        discounted_available = [p for p in discounted if p['id'] in user_products]
        if not discounted_available:
            bot.answer_callback_query(call.id, "❌ Нет доступных товаров со скидкой!")
            return

        keyboard = types.InlineKeyboardMarkup()
        for product in discounted_available:
            price_stars_disc, _, discount = get_product_price_with_discount(product)
            button_text = f"🔥 {product['name']} - {price_stars_disc}⭐ (-{discount}%)"
            if len(button_text) > 50:
                button_text = button_text[:47] + "..."
            keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"view:{product['id']}"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"🔥 Товары со скидкой:\n\n",
            reply_markup=keyboard
        )

    else:
        category_products = [p for p in user_products.values() if p['category'] == category]
        if not category_products:
            bot.answer_callback_query(call.id, "❌ В этой категории нет доступных товаров!")
            return

        keyboard = types.InlineKeyboardMarkup()
        for product in category_products:
            purchase_count = product.get('purchase_count', 0)
            button_text = f"{product['name']} - {product['price_stars']}⭐ ({purchase_count}👤)"
            if len(button_text) > 50:
                button_text = button_text[:47] + "..."
            keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"view:{product['id']}"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📁 Категория: {category}\n\nВыберите товар:",
            reply_markup=keyboard
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('model_'))
def show_model_products(call):
    user_products = get_available_products_for_user(call.from_user.id)
    model_name = call.data.replace('model_', '')
    model_products = [p for p in user_products.values() if p.get('model_name') == model_name]

    if not model_products:
        bot.answer_callback_query(call.id, "❌ У этой модели нет доступных товаров!")
        return

    model_products.sort(key=lambda x: x.get('purchase_count', 0), reverse=True)

    preview_path = get_model_preview_path(model_name)
    description = get_model_description(model_name)

    text = f"👤 Модель: {model_name}\n\n"
    if description:
        text += f"📝 {description}\n\n"

    if preview_path:
        with open(preview_path, 'rb') as photo:
            bot.send_photo(call.message.chat.id, photo, caption=text, protect_content=True)
    else:
        bot.send_message(call.message.chat.id, text)

    keyboard = types.InlineKeyboardMarkup()
    for product in model_products:
        purchase_count = product.get('purchase_count', 0)
        price_stars_disc, _, discount = get_product_price_with_discount(product)
        if discount:
            button_text = f"{product['name']} - ~~{product['price_stars']}⭐~~ {price_stars_disc}⭐ (-{discount}%) ({purchase_count}👤)"
        else:
            button_text = f"{product['name']} - {product['price_stars']}⭐ ({purchase_count}👤)"
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."
        keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"view:{product['id']}"))

    keyboard.add(types.InlineKeyboardButton("⬅️ Назад к моделям", callback_data="category_models"))
    bot.send_message(call.message.chat.id, "Товары модели:", reply_markup=keyboard)
    bot.delete_message(call.message.chat.id, call.message.message_id)

# ---------- ПРОСМОТР ТОВАРА ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('view:'))
def view_product(call):
    product_id = call.data.split(':', 1)[1]

    if product_id in products:
        product = products[product_id]
        user_id = call.from_user.id
        user_data = users.get(str(user_id), {})

        price_stars_disc, price_points_disc, discount = get_product_price_with_discount(product)
        original_price_stars = product['price_stars']
        original_price_points = original_price_stars * 2

        product_text = f"📦 {product['name']}\n\n"
        product_text += f"📝 {product['description']}\n\n"

        if discount:
            product_text += f"💰 ~~Цена: {original_price_stars} Stars / {original_price_points}🏆~~\n"
            product_text += f"💰 Цена со скидкой {discount}%: {price_stars_disc} Stars / {price_points_disc}🏆\n"
        else:
            product_text += f"💰 Цена: {original_price_stars} Stars / {original_price_points}🏆\n"

        product_text += f"🏷️ Категория: {product['category']}\n"

        if product.get('is_channel_access'):
            product_text += f"🔗 Тип: Доступ в канал\n"
        else:
            product_text += f"📁 Тип: {product.get('media_type', 'N/A')}\n"

        if product.get('blur_photos', False):
            product_text += f"🔒 Размытие фото: ✅ (фото будут размыты)\n"

        if product.get('auto_delete', False):
            product_text += f"⏰ Автоудаление: ✅ (через {product.get('auto_delete_minutes', 15)} минут)\n"

        product_text += f"🛒 Купили: {product.get('purchase_count', 0)} раз\n\n"
        product_text += f"🏆 Ваш баланс очков: {user_data.get('points', 0)}🏆"

        keyboard = types.InlineKeyboardMarkup(row_width=1)

        keyboard.add(types.InlineKeyboardButton(
            f"⭐ Купить за {price_stars_disc} Stars" + (" (скидка!)" if discount else ""),
            callback_data=f"buy_stars:{product_id}:{price_stars_disc}"
        ))

        user_points = user_data.get('points', 0)
        if user_points >= price_points_disc:
            keyboard.add(types.InlineKeyboardButton(
                f"🏆 Купить за {price_points_disc} очков" + (" (скидка!)" if discount else ""),
                callback_data=f"buy_points:{product_id}:{price_stars_disc}"
            ))
        else:
            keyboard.add(types.InlineKeyboardButton(
                f"🏆 Недостаточно очков (нужно {price_points_disc})",
                callback_data="not_enough_points"
            ))

        try:
            model_path = os.path.join(MODELS_DIR, product['model_name'])

            if product.get('cover_file'):
                cover_path = os.path.join(model_path, "covers", product['cover_file'])
                if os.path.exists(cover_path):
                    # Обложки не шифруем (публичные)
                    with open(cover_path, 'rb') as cover:
                        bot.send_photo(
                            call.message.chat.id,
                            cover,
                            caption=product_text,
                            reply_markup=keyboard,
                            protect_content=True
                        )
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                    return

            if product.get('media_files') and not product.get('is_channel_access'):
                media_path = os.path.join(model_path, product['media_type'], product['media_files'][0])
                if os.path.exists(media_path):
                    # Расшифровываем и отправляем первый файл как превью
                    temp_path = decrypt_file(media_path)
                    with open(temp_path, 'rb') as f:
                        if product['media_type'] == 'photo':
                            bot.send_photo(
                                call.message.chat.id,
                                f,
                                caption=product_text,
                                reply_markup=keyboard,
                                protect_content=True
                            )
                        else:
                            bot.send_video(
                                call.message.chat.id,
                                f,
                                caption=product_text,
                                reply_markup=keyboard,
                                protect_content=True
                            )
                    os.unlink(temp_path)
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                    return
        except Exception as e:
            print(f"Ошибка отправки медиа: {e}")

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=product_text,
            reply_markup=keyboard
        )
    else:
        bot.answer_callback_query(call.id, "❌ Товар не найден!")



# ---------- ОПЛАТА ----------
@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars:'))
def process_purchase_with_stars(call):
    parts = call.data.split(':')
    product_id = parts[1]
    price_paid = int(parts[2]) if len(parts) > 2 else None

    user_id = call.from_user.id

    if product_id not in products:
        bot.answer_callback_query(call.id, "❌ Товар не найден!")
        return

    product = products[product_id]
    order_id = generate_order_id()
    order = Order(
        order_id=order_id,
        user_id=user_id,
        product_id=product_id,
        status='pending',
        payment_method='stars',
        price_paid=price_paid or product['price_stars']
    )

    orders[order_id] = order.to_dict()
    save_data(ORDERS_FILE, orders)

    try:
        prices = [types.LabeledPrice(label=product['name'], amount=order.price_paid)]

        invoice_description = f"{product['description'][:255]}"
        if product.get('auto_delete', False):
            invoice_description += f"\n\n⚠️ Медиафайлы удалятся через {product.get('auto_delete_minutes', 15)} минут"
        if product.get('blur_photos', False):
            invoice_description += f"\n🔒 Фото будут размыты"
        if price_paid and price_paid != product['price_stars']:
            invoice_description += f"\n🎁 Скидка {discount}% активна!"

        invoice = bot.send_invoice(
            chat_id=call.message.chat.id,
            title=product['name'],
            description=invoice_description,
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter=order_id,
            invoice_payload=order_id,
            photo_url=None,
            photo_size=None,
            photo_width=None,
            photo_height=None,
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False,
            disable_notification=False,
            reply_to_message_id=None,
            allow_sending_without_reply=True,
            reply_markup=None
        )

        order_data = orders[order_id]
        order_data['invoice_message_id'] = invoice.message_id
        orders[order_id] = order_data
        save_data(ORDERS_FILE, orders)

        schedule_message_deletion(call.message.chat.id, invoice.message_id, 30)

    except Exception as e:
        print(f"Ошибка создания инвойса: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка при создании платежа. Попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_points:'))
def process_purchase_with_points(call):
    parts = call.data.split(':')
    product_id = parts[1]
    price_stars = int(parts[2]) if len(parts) > 2 else None

    user_id = call.from_user.id

    if product_id not in products:
        bot.answer_callback_query(call.id, "❌ Товар не найден!")
        return

    product = products[product_id]
    user_data = users.get(str(user_id))

    if not user_data:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден!")
        return

    if price_stars is None:
        price_stars = product['price_stars']

    price_points = price_stars * 2

    if user_data.get('points', 0) < price_points:
        bot.answer_callback_query(
            call.id,
            f"❌ Недостаточно очков!\nНужно: {price_points}🏆\nУ вас: {user_data.get('points', 0)}🏆"
        )
        return

    order_id = generate_order_id()
    order = Order(
        order_id=order_id,
        user_id=user_id,
        product_id=product_id,
        status='paid',
        payment_method='points',
        price_paid=price_stars
    )

    orders[order_id] = order.to_dict()
    save_data(ORDERS_FILE, orders)

    users[str(user_id)]['points'] -= price_points
    save_data(USERS_FILE, users)

    # Добавляем товар в список купленных
    if 'purchased_products' not in users[str(user_id)]:
        users[str(user_id)]['purchased_products'] = []
    if product_id not in users[str(user_id)]['purchased_products']:
        users[str(user_id)]['purchased_products'].append(product_id)
        save_data(USERS_FILE, users)

    send_product_to_user(user_id, product_id, order_id)
    products[product_id]['purchase_count'] = products[product_id].get('purchase_count', 0) + 1
    save_data(PRODUCTS_FILE, products)

    bot.answer_callback_query(call.id, "✅ Покупка успешно оплачена очками!")

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    order_id = pre_checkout_query.invoice_payload

    if order_id in orders and orders[order_id]['status'] == 'pending':
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    else:
        bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Заказ не найден или уже обработан"
        )

@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    order_id = message.successful_payment.invoice_payload

    if order_id in orders:
        order = orders[order_id]

        order['status'] = 'paid'
        order['paid_at'] = datetime.now().isoformat()
        orders[order_id] = order
        save_data(ORDERS_FILE, orders)

        product_id = order['product_id']
        if product_id in products:
            if 'purchase_count' not in products[product_id]:
                products[product_id]['purchase_count'] = 0
            products[product_id]['purchase_count'] += 1
            save_data(PRODUCTS_FILE, products)

        user_id = str(order['user_id'])
        if user_id in users:
            if 'orders' not in users[user_id]:
                users[user_id]['orders'] = []
            users[user_id]['orders'].append(order_id)

            # Добавляем товар в список купленных
            if 'purchased_products' not in users[user_id]:
                users[user_id]['purchased_products'] = []
            if product_id not in users[user_id]['purchased_products']:
                users[user_id]['purchased_products'].append(product_id)

            save_data(USERS_FILE, users)

        award_referral_stars_purchase_bonus(order['user_id'])
        send_product_to_user(order['user_id'], product_id, order_id)

        try:
            if 'invoice_message_id' in order:
                bot.delete_message(message.chat.id, order['invoice_message_id'])
        except:
            pass

# ---------- ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ----------
@bot.callback_query_handler(func=lambda call: call.data == 'show_my_points')
def show_my_points(call):
    user_id = str(call.from_user.id)
    user_data = users.get(user_id, {})

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"🏆 Ваши очки: {user_data.get('points', 0)}🏆\n\n"
        f"2🏆 = 1⭐ при оплате товаров!\n\n"
        f"🎯 Как заработать больше?\n"
        f"• Ежедневный вход: +20🏆\n"
        f"• Приглашение друга: +50🏆\n"
        f"• Покупка реферала: +20🏆 (ТОЛЬКО за Telegram Stars)"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'show_my_referrals')
def show_my_referrals(call):
    user_id = str(call.from_user.id)

    referrals = []
    for uid, user_data in users.items():
        if str(user_data.get('referred_by')) == user_id:
            referrals.append(user_data)

    if not referrals:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "📭 У вас еще нет рефералов")
        return

    ref_text = "👥 Ваши рефералы:\n\n"

    for i, ref in enumerate(referrals[:20], 1):
        ref_text += f"{i}. @{ref.get('username', 'No username')}\n"

    if len(referrals) > 20:
        ref_text += f"\n📄 Показано 20 из {len(referrals)} рефералов"

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, ref_text)

@bot.callback_query_handler(func=lambda call: call.data == 'show_my_tasks')
def show_my_tasks_callback(call):
    user_id = str(call.from_user.id)

    if user_id not in users:
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "❌ Пользователь не найден!")
        return

    user_data = users[user_id]

    if 'daily_login' not in tasks:
        tasks['daily_login'] = {
            'name': 'Ежедневный вход',
            'description': 'Зайдите в бота каждый день',
            'points': 20,
            'type': 'daily',
            'cooldown_hours': 24
        }

    if 'referral' not in tasks:
        tasks['referral'] = {
            'name': 'Реферальная система',
            'description': 'Пригласите друга по своей реферальной ссылке',
            'points': 50,
            'type': 'one_time',
            'bonus_per_purchase': 20
        }

    tasks_text = "🎯 Ваши задания:\n\n"

    daily_task = tasks['daily_login']
    last_login = user_data.get('last_daily_login')

    if last_login:
        try:
            last_login_date = datetime.fromisoformat(last_login).date()
            today = datetime.now().date()

            if last_login_date == today:
                status = "✅ Выполнено сегодня"
            else:
                status = "🔄 Доступно"
        except:
            status = "🔄 Доступно"
    else:
        status = "🔄 Доступно"

    tasks_text += f"1. {daily_task['name']}\n"
    tasks_text += f"   Награда: {daily_task['points']}🏆\n"
    tasks_text += f"   Статус: {status}\n"
    tasks_text += f"   Серия дней: {user_data.get('daily_login_streak', 0)}\n\n"

    ref_task = tasks['referral']
    referral_count = count_user_referrals(user_id)

    tasks_text += f"2. {ref_task['name']}\n"
    tasks_text += f"   Награда: {ref_task['points']}🏆 за каждого\n"
    tasks_text += f"   Приглашено: {referral_count} человек\n\n"

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, tasks_text)

@bot.callback_query_handler(func=lambda call: call.data == 'not_enough_points')
def not_enough_points(call):
    bot.answer_callback_query(call.id, "🏆 Зарабатывайте очки, выполняя задания в разделе '🎯 Задания'")

# ---------- ЗАПУСК БОТА ----------
if __name__ == '__main__':
    ensure_voting_week()

    while True:
        try:
            print("🚀 Бот запущен")
            bot.polling(
                non_stop=True,
                interval=1,
                timeout=60,
                long_polling_timeout=60
            )
        except Exception as e:
            logging.exception("❌ Ошибка polling, перезапуск через 5 сек")
            time.sleep(5)