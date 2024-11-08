import dataclasses
import re
import json
import os
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup, Tag, PageElement
import schedule as scheduler
import time as time_module

def get_semester_and_group_number(current_date: datetime) -> (str, str):
    if current_date.month in [9, 10, 11, 12]:
        semester = "osenniy"
    else:
        semester = "vesenniy"

    group_number = "your_group"

    if current_date.month == 7:
        number_part = ''.join(filter(lambda x: x.isdigit(), group_number))
        letter_part = ''.join(filter(lambda x: x.isalpha(), group_number))
        number_part = str(int(number_part) + 100)
        group_number = number_part + letter_part

    return semester, group_number

current_date = datetime.now()
semester, group_number = get_semester_and_group_number(current_date)
TABLE_URL = f"https://www.sibstrin.ru/timetable/group/{semester}/{group_number}.htm"
TIME_REGEX = re.compile(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})')
JSON_FILE = 'univBase.json'


@dataclasses.dataclass
class Lesson:
    def __init__(self, date, weekday, start_time, end_time, payload, building=None):
        if "Элективные курсы по физической культуре и спорту" in payload:
            payload = payload[:-12]
            building = ""
        self.date = date
        self.weekday = weekday
        self.start_time = start_time
        self.end_time = end_time
        self.payload = payload
        self.building = building
        self.group, self.subject, self.teacher, self.location = self.parse_payload(payload)


    @classmethod
    def create(cls, *, time_cell: Tag, date_cell: Tag, weekday_cell: Tag, lesson_cell: Tag) -> 'Lesson':
        start_time_str, end_time_str = TIME_REGEX.match(time_cell.get_text(strip=True)).groups()
        payload = lesson_cell.get_text(strip=True)
        room_match = re.findall(r'(\d+)[а-яА-Я]?', payload)
        building = "Неизвестный корпус"
        if room_match:
            room_number = int(room_match[-1])
            building = get_building_by_room(room_number)

        return cls(
            date=datetime.strptime(date_cell.get_text(strip=True), '%d.%m.%Y').date(),
            weekday=weekday_cell.get_text(strip=True),
            start_time=datetime.strptime(start_time_str, '%H:%M').time(),
            end_time=datetime.strptime(end_time_str, '%H:%M').time(),
            payload=payload,
            building=building
        )


    @staticmethod
    def parse_payload(payload: str):
        group_match = re.search(r'(\d+.*?\s*гр\.)', payload)
        group = group_match.group(0) if group_match else ''
        payload = payload.replace(group, '').strip()
        lesson_type_location_match = re.search(r'([А-Яа-я]+\./\s*\d+[а-яА-Я]?\s*ауд\.)', payload)
        if not lesson_type_location_match:
            lesson_type_location_match = re.search(r'([А-Яа-я]+\s*[А-Яа-я]+\s*/\s*\d+[а-яА-Я]?\s*ауд\.)', payload)
        location = lesson_type_location_match.group(0) if lesson_type_location_match else ''  # Место занятия.
        payload = payload.replace(location, '').strip()
        teacher_match = re.search(r'([А-Я][а-я]+\s+[А-Я]\.\s*[А-Я]\.)', payload)
        teacher = teacher_match.group(0) if teacher_match else ''
        payload = payload.replace(teacher, '').strip()
        subject = payload.strip().upper()

        return group, subject, teacher, location


def get_building_by_room(room_number: int) -> str:
    if 102 <= room_number <= 122 or 202 <= room_number <= 239 or 302 <= room_number <= 326 or 401 <= room_number <= 428:
        return "Главный корпус."
    elif 132 <= room_number <= 139 or 240 <= room_number <= 251 or 338 <= room_number <= 347 or 433 <= room_number <= 438 or 504 <= room_number <= 511:
        return "Пристройка главного корпуса."
    elif 291 <= room_number <= 296 or 391 <= room_number <= 396:
        return "Учебный корпус №3."
    elif 4001 <= room_number <= 4309:
        return "Учебный корпус №4."
    elif 151 <= room_number <= 181 or 255 <= room_number <= 285 or 351 <= room_number <= 382:
        return "Лабораторный корпус."
    else:
        return "Неизвестный корпус."


def get_rowspan(cell: Tag) -> int:
    return int(cell.get('rowspan', '1'))


def get_next_tag_sibling(element: PageElement) -> Tag:
    return next(s for s in element.next_siblings if isinstance(s, Tag))


def parse_lessons() -> list[Lesson]:
    response = requests.get(TABLE_URL, verify=False)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    time_row = soup.find('tr', class_='R3')
    assert time_row, 'No time header'
    time_cells = time_row.find_all('td')
    assert time_cells, 'No times'
    rows = soup.find_all('tr', class_='R4')
    lessons = []
    for row in rows:
        row_cells = row.find_all('td')
        maybe_week_cell, *other_cells = row_cells

        if get_rowspan(maybe_week_cell) > 2:
            row_cells = other_cells

        weekday_cell, date_cell, *lesson_cells = row_cells
        rowspan = get_rowspan(weekday_cell)
        assert rowspan in (1, 2)
        skip_lesson_in_next_rows = 0

        for time_cell, lesson_cell in zip(time_cells[3:], lesson_cells):
            if not time_cell.get_text(strip=True):
                continue
            if not lesson_cell.get_text(strip=True):
                continue

            lessons.append(
                Lesson.create(
                    time_cell=time_cell,
                    date_cell=date_cell,
                    weekday_cell=weekday_cell,
                    lesson_cell=lesson_cell,
                )
            )

            if rowspan == 2 and get_rowspan(lesson_cell) == 1:
                next_row = get_next_tag_sibling(row)
                next_row_cells = next_row.find_all('td')
                lesson_cell = next_row_cells[skip_lesson_in_next_rows]
                lessons.append(
                    Lesson.create(
                        time_cell=time_cell,
                        date_cell=date_cell,
                        weekday_cell=weekday_cell,
                        lesson_cell=lesson_cell,
                    )
                )
                skip_lesson_in_next_rows += 1

    return lessons


def split_lesson_by_week(lessons: list[Lesson]) -> dict:
    first_week = []
    second_week = []

    for lesson in lessons:
        if (lesson.date.isocalendar()[1] % 2) == 1:
            first_week.append(lesson)
        else:
            second_week.append(lesson)

    first_week.sort(key=lambda l: (l.date, l.start_time))
    second_week.sort(key=lambda l: (l.date, l.start_time))

    return {
        "lessons": {
            "first_week": first_week,
            "second_week": second_week,
        }
    }


def save_lesson_to_json(lessons_by_week: dict):
    formatted_data = {
        "lessons": {
            "first_week": [],
            "second_week": []
        }
    }

    weekdays_translation = {
        'Monday': 'Пн.',
        'Tuesday': 'Вт.',
        'Wednesday': 'Ср.',
        'Thursday': 'Чт.',
        'Friday': 'Пт.',
        'Saturday': 'Сб.',
        'Sunday': 'Вс.'
    }

    for week, lessons in zip(["first_week", "second_week"],
                             [lessons_by_week["lessons"]["first_week"],
                              lessons_by_week["lessons"]["second_week"]]):

        if week == "first_week":
            formatted_data["lessons"][week].append("Расписание на первую неделю:\n\n")
        else:
            formatted_data["lessons"][week].append("Расписание на вторую неделю:\n\n")

        lesson_dates = {lesson.date for lesson in lessons}

        if lessons:
            start_date = min(lesson.date for lesson in lessons)
            date_range = [start_date + timedelta(days=i) for i in range(7)]
        else:
            date_range = []

        for date in date_range:
            weekday_name = date.strftime('%A')
            short_weekday = weekdays_translation.get(weekday_name, weekday_name)

            if date in lesson_dates:
                for lesson in lessons:
                    if lesson.date == date:
                        formatted_data["lessons"][week].append(
                            f"{lesson.date.strftime('%d.%m.%Y')} | {short_weekday}\n"
                            f"[{lesson.start_time.strftime('%H:%M')} - {lesson.end_time.strftime('%H:%M')}]\n"
                            f"Предмет: {lesson.subject}.\n"
                            f"Преподаватель: {lesson.teacher}\n"
                            f"Аудитория: {lesson.location}\n"
                            f"Корпус: {lesson.building}\n\n"
                        )
            else:
                formatted_data["lessons"][week].append(
                    f"{date.strftime('%d.%m.%Y')} | {short_weekday}\n"
                    f"Выходной! Нет ничего лучше выходных, правда?\n\n"
                )

    if os.path.exists(JSON_FILE):
        os.remove(JSON_FILE)

    with open(JSON_FILE, 'w', encoding='utf-8') as file:
        json.dump(formatted_data, file, ensure_ascii=False, indent=4)


def update_lesson():
    lessons = parse_lessons()
    lessons_by_week = split_lesson_by_week(lessons)
    save_lesson_to_json(lessons_by_week)
    print(f"Расписание обновлено и сохранено в {JSON_FILE}.")

scheduler.every().day.at("10:00").do(update_lesson)
scheduler.every().day.at("22:00").do(update_lesson)

if __name__ == "__main__":
    update_lesson()
    while True:
        scheduler.run_pending()
        time_module.sleep(1)
