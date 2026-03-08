import os
import json
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from supabase import create_client, Client

load_dotenv()

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
server = Server("muninn-memory")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="save_conversation", description="Salva mensagem no histórico",
             inputSchema={"type":"object","properties":{"session_id":{"type":"string"},"role":{"type":"string"},"content":{"type":"string"}},"required":["session_id","role","content"]}),
        Tool(name="get_conversation", description="Recupera histórico",
             inputSchema={"type":"object","properties":{"session_id":{"type":"string"},"limit":{"type":"integer"}},"required":["session_id"]}),
        Tool(name="save_memory", description="Salva nota, preferencia ou resultado",
             inputSchema={"type":"object","properties":{"type":{"type":"string","enum":["note","preference","result"]},"title":{"type":"string"},"content":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["type","title","content"]}),
        Tool(name="get_memories", description="Busca memorias por tipo/tags",
             inputSchema={"type":"object","properties":{"type":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"limit":{"type":"integer"}}}),
        Tool(name="search_memories", description="Busca memorias por texto",
             inputSchema={"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}),
        Tool(name="create_calendar_event", description="Cria evento no Google Calendar",
             inputSchema={"type":"object","properties":{"title":{"type":"string"},"start":{"type":"string"},"end":{"type":"string"},"description":{"type":"string"},"location":{"type":"string"},"guests":{"type":"array","items":{"type":"string"}}},"required":["title","start"]}),
        Tool(name="list_calendar_events", description="Lista proximos eventos do Google Calendar",
             inputSchema={"type":"object","properties":{"max_results":{"type":"integer"}}}),
        Tool(name="create_google_task", description="Cria tarefa no Google Tasks",
             inputSchema={"type":"object","properties":{"title":{"type":"string"},"notes":{"type":"string"},"due":{"type":"string"}},"required":["title"]}),
        Tool(name="list_google_tasks", description="Lista tarefas pendentes do Google Tasks",
             inputSchema={"type":"object","properties":{"max_results":{"type":"integer"}}}),
        Tool(name="delete_calendar_event", description="Deleta evento do Google Calendar pelo ID",
             inputSchema={"type":"object","properties":{"google_event_id":{"type":"string"},"title":{"type":"string"}},"required":["google_event_id"]}),
        Tool(name="update_calendar_event", description="Atualiza evento existente no Google Calendar",
             inputSchema={"type":"object","properties":{"google_event_id":{"type":"string"},"title":{"type":"string"},"start":{"type":"string"},"end":{"type":"string"},"description":{"type":"string"},"location":{"type":"string"}},"required":["google_event_id"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "save_conversation":
            supabase.table("conversations").insert(arguments).execute()
            return [TextContent(type="text", text="ok")]

        elif name == "get_conversation":
            r = (supabase.table("conversations")
                .select("role,content,created_at")
                .eq("session_id", arguments["session_id"])
                .order("created_at")
                .limit(arguments.get("limit", 20))
                .execute())
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]

        elif name == "save_memory":
            supabase.table("memories").insert({
                **arguments,
                "tags": arguments.get("tags", [])
            }).execute()
            return [TextContent(type="text", text=f"Memoria '{arguments['title']}' salva.")]

        elif name == "get_memories":
            q = supabase.table("memories").select("*")
            if "type" in arguments:
                q = q.eq("type", arguments["type"])
            if arguments.get("tags"):
                q = q.overlaps("tags", arguments["tags"])
            r = q.order("created_at", desc=True).limit(arguments.get("limit", 10)).execute()
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]

        elif name == "search_memories":
            query = arguments["query"]
            r = (supabase.table("memories")
                .select("*")
                .or_(f"title.ilike.%{query}%,content.ilike.%{query}%")
                .limit(arguments.get("limit", 10))
                .execute())
            if not r.data:
                r = (supabase.table("memories")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(arguments.get("limit", 10))
                    .execute())
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]

        elif name == "create_calendar_event":
            from google_tools import create_event
            from datetime import timedelta
            result = create_event(
                title=arguments["title"],
                start=arguments["start"],
                end=arguments.get("end"),
                description=arguments.get("description", ""),
                location=arguments.get("location", ""),
                guests=arguments.get("guests", [])
            )
            supabase.table("events").insert({
                "title": arguments["title"],
                "description": arguments.get("description", ""),
                "start_at": arguments["start"],
                "end_at": arguments.get("end", arguments["start"]),
                "location": arguments.get("location", ""),
                "google_event_id": result["google_event_id"],
                "google_calendar_id": os.getenv("GOOGLE_MUNINN_EMAIL"),
                "guests": arguments.get("guests", [os.getenv("GOOGLE_PERSONAL_EMAIL")]),
                "status": "confirmed"
            }).execute()
            return [TextContent(type="text", text=f"Evento criado: {arguments['title']} em {arguments['start']}. ID: {result['google_event_id']}")]
        elif name == "list_calendar_events":
            from google_tools import list_events
            events = list_events(max_results=arguments.get("max_results", 10))
            if not events:
                return [TextContent(type="text", text="Nenhum evento proximo encontrado.")]
            lines = [f"• {e['start']} — {e['title']}{(' @ ' + e['location']) if e['location'] else ''}" for e in events]
            return [TextContent(type="text", text="\n".join(lines))]
        elif name == "create_google_task":
            from google_tools import create_task
            result = create_task(
                title=arguments["title"],
                notes=arguments.get("notes", ""),
                due=arguments.get("due")
            )
            return [TextContent(type="text", text=f"Tarefa criada: {result['title']}. ID: {result['task_id']}")]
        elif name == "list_google_tasks":
            from google_tools import list_tasks
            tasks = list_tasks(max_results=arguments.get("max_results", 10))
            if not tasks:
                return [TextContent(type="text", text="Nenhuma tarefa pendente.")]
            lines = [f"• {t['title']}{(' — ' + t['notes']) if t['notes'] else ''}{(' (vence: ' + t['due'] + ')') if t['due'] else ''}" for t in tasks]
            return [TextContent(type="text", text="\n".join(lines))]
        elif name == "delete_calendar_event":
            from google_tools import delete_event
            delete_event(arguments["google_event_id"])
            supabase.table("events").update({"status": "cancelled"}).eq("google_event_id", arguments["google_event_id"]).execute()
            return [TextContent(type="text", text=f"Evento deletado: {arguments.get('title', arguments['google_event_id'])}")]
        elif name == "update_calendar_event":
            from google_tools import update_event
            result = update_event(
                google_event_id=arguments["google_event_id"],
                title=arguments.get("title"),
                start=arguments.get("start"),
                end=arguments.get("end"),
                description=arguments.get("description"),
                location=arguments.get("location")
            )
            supabase.table("events").update({
                k: v for k, v in {
                    "title": arguments.get("title"),
                    "start_at": arguments.get("start"),
                    "end_at": arguments.get("end"),
                    "description": arguments.get("description"),
                    "location": arguments.get("location")
                }.items() if v is not None
            }).eq("google_event_id", arguments["google_event_id"]).execute()
            return [TextContent(type="text", text=f"Evento atualizado: {result['title']} em {result['start']}")]
        else:
            return [TextContent(type="text", text=f"Ferramenta desconhecida: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Erro: {str(e)}")]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
