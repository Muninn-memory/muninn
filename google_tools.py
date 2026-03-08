import os
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google_auth import get_credentials
from dotenv import load_dotenv

load_dotenv()

PERSONAL_EMAIL = os.getenv("GOOGLE_PERSONAL_EMAIL", "")
MUNINN_EMAIL = os.getenv("GOOGLE_MUNINN_EMAIL", "")


def get_calendar_service():
    return build("calendar", "v3", credentials=get_credentials())


def get_tasks_service():
    return build("tasks", "v1", credentials=get_credentials())


def create_event(title: str, start: str, end: str = None,
                 description: str = "", location: str = "",
                 guests: list = None) -> dict:
    """Cria evento no Google Calendar e convida o email pessoal."""
    service = get_calendar_service()

    if guests is None:
        guests = []
    if PERSONAL_EMAIL and PERSONAL_EMAIL not in guests:
        guests.append(PERSONAL_EMAIL)

    attendees = [{"email": g} for g in guests]

    # Se end não informado, assume 1h depois
    if not end:
        from dateutil import parser
        from datetime import timedelta
        dt = parser.parse(start)
        end = (dt + timedelta(hours=1)).isoformat()

    event_body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start, "timeZone": "America/Sao_Paulo"},
        "end": {"dateTime": end, "timeZone": "America/Sao_Paulo"},
        "attendees": attendees,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 60},
                {"method": "popup", "minutes": 15},
            ],
        },
    }

    result = service.events().insert(
        calendarId=MUNINN_EMAIL,
        body=event_body,
        sendUpdates="all"
    ).execute()

    return {
        "google_event_id": result["id"],
        "html_link": result.get("htmlLink", ""),
        "status": result.get("status", "confirmed"),
    }


def list_events(max_results: int = 10, time_min: str = None) -> list:
    """Lista próximos eventos do calendário."""
    service = get_calendar_service()
    if not time_min:
        time_min = datetime.now(timezone.utc).isoformat()

    result = service.events().list(
        calendarId=MUNINN_EMAIL,
        timeMin=time_min,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = []
    for e in result.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date"))
        events.append({
            "id": e["id"],
            "title": e.get("summary", "Sem título"),
            "start": start,
            "location": e.get("location", ""),
        })
    return events


def delete_event(google_event_id: str) -> bool:
    """Cancela/deleta um evento pelo ID."""
    service = get_calendar_service()
    service.events().delete(
        calendarId=MUNINN_EMAIL,
        eventId=google_event_id
    ).execute()
    return True


def create_task(title: str, notes: str = "", due: str = None) -> dict:
    """Cria uma tarefa no Google Tasks."""
    service = get_tasks_service()
    task_body = {"title": title, "notes": notes}
    if due:
        task_body["due"] = due

    tasklists = service.tasklists().list().execute()
    tasklist_id = tasklists["items"][0]["id"]

    result = service.tasks().insert(
        tasklist=tasklist_id,
        body=task_body
    ).execute()

    return {"task_id": result["id"], "title": result["title"]}


def list_tasks(max_results: int = 10) -> list:
    """Lista tarefas pendentes."""
    service = get_tasks_service()
    tasklists = service.tasklists().list().execute()
    tasklist_id = tasklists["items"][0]["id"]

    result = service.tasks().list(
        tasklist=tasklist_id,
        maxResults=max_results,
        showCompleted=False
    ).execute()

    return [
        {"id": t["id"], "title": t["title"], "due": t.get("due", ""), "notes": t.get("notes", "")}
        for t in result.get("items", [])
    ]
