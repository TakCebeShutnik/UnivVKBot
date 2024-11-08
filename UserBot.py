from vkbottle.bot import Bot
import asyncio
import nest_asyncio
from datetime import datetime, timedelta
import json
import os

bot = Bot("token")
AUTHORIZED_USER_IDS = ["user_id"]
bot_enabled = True
message_count = 0
last_reset_time = datetime.now()
reminders = {}
last_command_time = {}


async def reset_message_count():
    global message_count
    await asyncio.sleep(180)
    message_count = 0


async def send_and_delete_message(peer_ids, message_text):
    response = await bot.api.messages.send(
        peer_ids=peer_ids,
        message=message_text,
        random_id=0
    )

    if not isinstance(response, list):
        response = [response]

    for peer_id, result in zip(peer_ids if isinstance(peer_ids, list) else [peer_ids], response):
        conversation_message_id = result.conversation_message_id
        if conversation_message_id:
            await asyncio.sleep(600)
            await bot.api.messages.delete(
                cmids=[conversation_message_id],
                peer_id=peer_id,
                delete_for_all=True
            )


async def send_message_with_limit(peer_id, text):
    global message_count, last_reset_time
    now = datetime.now()

    if (now - last_reset_time).seconds > 180:
        message_count = 0
        last_reset_time = now

    if message_count < 8:
        await send_and_delete_message(peer_id, text)
        message_count += 1

        if message_count == 8:
            await bot.api.messages.send(peer_id=peer_id, message="Мне нужно отдохнуть, отвечу через 3 минуты.", random_id=0)
            await reset_message_count()


def load_lessons_from_json():
    with open('univBase.json', 'r', encoding='utf-8') as file:
        data = json.load(file)
        first_week_lessons = data['lessons']['first_week']
        second_week_lessons = data['lessons']['second_week']
        return first_week_lessons, second_week_lessons


async def update_lessons_periodically():
    while True:
        now = datetime.now()
        if (now.hour == 10 and now.minute == 1) or (now.hour == 20 and now.minute == 1):
            print("Обновление расписания...")
            load_lessons_from_json()
        await asyncio.sleep(60)


def get_schedule_by_date(lessons, target_date):
    target_date_str = target_date.strftime('%d.%m.%Y')
    return [lesson for lesson in lessons if target_date_str in lesson]


def get_current_class(lessons):
    now = datetime.now()
    today = now.date()
    current_lesson = None

    for lesson in lessons:
        lesson_date_str = lesson.split('|')[0].strip()
        lesson_start_str = lesson.split('[')[1].split(']')[0].strip().split(' - ')[0]
        lesson_end_str = lesson.split('[')[1].split(']')[0].strip().split(' - ')[1]
        lesson_start = datetime.strptime(f"{lesson_date_str} {lesson_start_str}", '%d.%m.%Y %H:%M')
        lesson_end = datetime.strptime(f"{lesson_date_str} {lesson_end_str}", '%d.%m.%Y %H:%M')

        if lesson_start.date() == today and lesson_start <= now <= lesson_end:
            current_lesson = lesson
            break

    return current_lesson


async def set_reminder(minutes_before, peer_id, first_week_lessons, second_week_lessons):
    today = datetime.now().date()
    current_time = datetime.now()
    all_lessons = first_week_lessons + second_week_lessons

    today_lessons = [
        lesson_info for lesson_info in all_lessons
        if "Предмет:" in lesson_info and
           datetime.strptime(lesson_info.split('|')[0].strip(), '%d.%m.%Y').date() == today and
           datetime.strptime(f"{lesson_info.split('|')[0].strip()} {lesson_info.split('[')[1].split(' - ')[0]}",
                             '%d.%m.%Y %H:%M') > current_time
    ]

    if today_lessons:
        reminders_to_set = []
        for lesson_info in today_lessons:
            lesson_time_str = lesson_info.split("\n")[1][1:-1].split(" - ")[0]
            lesson_date_str = lesson_info.split('|')[0].strip()
            lesson_time = datetime.strptime(f"{lesson_date_str} {lesson_time_str}", '%d.%m.%Y %H:%M')

            reminder_time = lesson_time - timedelta(minutes=minutes_before)
            reminder_key = f"{peer_id}_{lesson_time.strftime('%Y%m%d%H%M')}"

            reminders[reminder_key] = {
                "time": reminder_time,
                "lesson_info": lesson_info,
                "minutes_before": minutes_before,
                "peer_id": peer_id
            }

            reminders_to_set.append(f"Напоминание установлено на {reminder_time.strftime('%H:%M')} для пары:\n{lesson_info}")

        response = "\n\n".join(reminders_to_set)
        await send_message_with_limit(peer_id, response)
    else:
        response = "Нет предстоящих пар для напоминания на сегодня."
        await send_message_with_limit(peer_id, response)


async def cancel_reminder(peer_id):
    reminders_to_delete = [key for key in reminders if key.startswith(str(peer_id))]

    if reminders_to_delete:
        for reminder_key in reminders_to_delete:
            del reminders[reminder_key]
        response = "Все напоминания отменены."
    else:
        response = "Нет установленных напоминаний для отмены."
    await send_message_with_limit(peer_id, response)


async def check_reminders():
    while True:
        current_time = datetime.now()
        for reminder_key, reminder_data in list(reminders.items()):
            if current_time >= reminder_data["time"]:
                minutes_before = reminder_data["minutes_before"]
                lesson_info = reminder_data["lesson_info"]
                peer_id = reminder_data["peer_id"]
                subject_line = [line for line in lesson_info.split("\n") if "Предмет:" in line][0]
                subject = subject_line.split(": ")[1].strip()

                response = f"\n!!!Напоминание!!!\n\nЧерез {minutes_before} минут начнется \n|{subject}|\n{lesson_info}"
                await send_message_with_limit(peer_id, response)
                del reminders[reminder_key]
        await asyncio.sleep(60)


@bot.on.message()
async def handle_commands(message):
    global message_count, bot_enabled
    command = message.text.lower()
    first_week_lessons, second_week_lessons = load_lessons_from_json()
    now = datetime.now()

    if message.from_id in AUTHORIZED_USER_IDS and message.peer_id == message.from_id:
        if command == "-off":
            await bot.api.messages.send(
                peer_id=message.peer_id,
                message="Выключение системы...",
                random_id=0)
            os.system('shutdown /s /t 0')
            return

        elif command == "-srn":
            await bot.api.messages.send(
                peer_id=message.peer_id,
                message="Перезагрузка системы...",
                random_id=0)
            os.system("shutdown /r /t 1")
            return

        elif command == "+deaf":
            bot_enabled = False
            await bot.api.messages.send(
                peer_id=message.peer_id,
                message="Функционал бота отключен.",
                random_id=0
            )
            return

        elif command == "-deaf":
            bot_enabled = True
            await bot.api.messages.send(
                peer_id=message.peer_id,
                message="Функционал бота включен.",
                random_id=0
            )
            return

    if not bot_enabled:
        return

    if command in last_command_time and (now - last_command_time[command]).total_seconds() < 5:
        return

    last_command_time[command] = now

    if command == "бот расписание сегодня" or command == "брс":
        today = datetime.now()
        today_lessons = get_schedule_by_date(first_week_lessons, today) or get_schedule_by_date(second_week_lessons, today)
        response = "Расписание на сегодня:\n\n" + "\n".join(today_lessons) if today_lessons else "Расписание на сегодня недоступно."
        await send_message_with_limit(message.peer_id, response)

    elif command == "бот расписание завтра" or command == "брз":
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_lessons = get_schedule_by_date(first_week_lessons, tomorrow) or get_schedule_by_date(second_week_lessons, tomorrow)
        response = "Расписание на завтра:\n\n" + "\n".join(tomorrow_lessons) if tomorrow_lessons else "Расписание на завтра недоступно."
        await send_message_with_limit(message.peer_id, response)

    elif command == "бот расписание 1 неделя" or command == "бр1":
        response = "\n".join(first_week_lessons) if first_week_lessons else "Расписание на первую неделю недоступно."
        await send_message_with_limit(message.peer_id, response)

    elif command == "бот расписание 2 неделя" or command == "бр2":
        response = "\n".join(second_week_lessons) if second_week_lessons else "Расписание на вторую неделю недоступно."
        await send_message_with_limit(message.peer_id, response)

    elif command == "бот пара сейчас" or command == "бпс":
        today = datetime.now()
        today_lessons = get_schedule_by_date(first_week_lessons, today) or get_schedule_by_date(second_week_lessons, today)
        current_lesson = get_current_class(today_lessons)
        response = "Сейчас пара:\n\n" + current_lesson if current_lesson else "Сейчас нет активных пар."
        await send_message_with_limit(message.peer_id, response)

    elif command.startswith("бот напомни") or command.startswith("бн"):
        try:
            if command.startswith("бот напомни"):
                minutes_before = int(command.split()[2])
            else:
                minutes_before = int(command.split()[1])
            await set_reminder(minutes_before, message.peer_id, first_week_lessons, second_week_lessons)
        except (ValueError, IndexError):
            await send_message_with_limit(message.peer_id, "Укажите правильное количество минут.")

    elif command == "бот не напоминай" or command == "небн":
        await cancel_reminder(message.peer_id)

    elif command == "бот команды" or command == "бк":
        commands_list = """
        Доступные команды:
    1. "Бот расписание сегодня/брс" - расписание на сегодня.
    2. "Бот расписание завтра/брз" - расписание на завтра.
    3. "Бот расписание 1 неделя/бр1" - расписание на первую неделю.
    4. "Бот расписание 2 неделя/бр2" - расписание на вторую неделю.
    5. "Бот напомни [число]/бн [число]" - установить напоминание.
    6. "Бот не напоминай/небн" - отключить напоминание.
    7. "Бот пара сейчас/бпс" - текущая пара.
    8. "Бот команды/бк" - меню.
        """
        await send_message_with_limit(message.peer_id, commands_list)


if __name__ == "__main__":
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.create_task(check_reminders())
    loop.create_task(update_lessons_periodically())
    bot.run_forever()
