from __future__ import annotations

from muninn_bridge import call_muninn


async def check_calendar(*, max_results: int = 10) -> str:
    return await call_muninn(
        "list_calendar_events",
        {"max_results": max(1, int(max_results))},
    )


async def create_event(
    *,
    title: str,
    start: str,
    end: str | None = None,
    description: str = "",
    location: str = "",
    guests: list[str] | None = None,
) -> str:
    args: dict[str, object] = {
        "title": title,
        "start": start,
        "description": description,
        "location": location,
        "guests": guests or [],
    }
    if end:
        args["end"] = end
    return await call_muninn("create_calendar_event", args)


async def list_tasks(*, max_results: int = 10) -> str:
    return await call_muninn("list_google_tasks", {"max_results": max(1, int(max_results))})


async def create_task(*, title: str, notes: str = "", due: str | None = None) -> str:
    args: dict[str, object] = {"title": title, "notes": notes}
    if due:
        args["due"] = due
    return await call_muninn("create_google_task", args)
