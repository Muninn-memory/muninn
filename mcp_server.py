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
        Tool(name="save_memory", description="Salva nota, preferência ou resultado",
             inputSchema={"type":"object","properties":{"type":{"type":"string","enum":["note","preference","result"]},"title":{"type":"string"},"content":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["type","title","content"]}),
        Tool(name="get_memories", description="Busca memórias por tipo/tags",
             inputSchema={"type":"object","properties":{"type":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"limit":{"type":"integer"}}}),
        Tool(name="search_memories", description="Busca memórias por texto",
             inputSchema={"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "save_conversation":
            supabase.table("conversations").insert(arguments).execute()
            return [TextContent(type="text", text="ok")]
        elif name == "get_conversation":
            r = supabase.table("conversations").select("role,content,created_at").eq("session_id",arguments["session_id"]).order("created_at").limit(arguments.get("limit",20)).execute()
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]
        elif name == "save_memory":
            supabase.table("memories").insert({**arguments,"tags":arguments.get("tags",[])}).execute()
            return [TextContent(type="text", text=f"Memória '{arguments['title']}' salva.")]
        elif name == "get_memories":
            q = supabase.table("memories").select("*")
            if "type" in arguments: q = q.eq("type", arguments["type"])
            if arguments.get("tags"): q = q.overlaps("tags", arguments["tags"])
            r = q.order("created_at", desc=True).limit(arguments.get("limit",10)).execute()
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]
        elif name == "search_memories":
            query = arguments['query']
            r = (
                supabase.table("memories")
                .select("*")
                .or_(f"title.ilike.%{query}%,content.ilike.%{query}%")
                .limit(arguments.get("limit", 10))
                .execute()
            )
            if not r.data:
                r = (
                    supabase.table("memories")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(arguments.get("limit", 10))
                    .execute()
                )
            return [TextContent(type="text", text=json.dumps(r.data, ensure_ascii=False))]

async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
