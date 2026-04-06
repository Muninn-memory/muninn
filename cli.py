from __future__ import annotations

import asyncio
import os

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

# Hardening for local Windows execution before Huginn imports.
os.environ.setdefault("PYTHONUTF8", "1")

from huginn.config import get_settings
from huginn.logging_config import configure_logging
from huginn_pipeline import run_huginn_query
from muninn import (
    DEFAULT_MODEL,
    DeepseekMode,
    muninn_app,
    run_muninn_chat,
    run_muninn_memory,
)

load_dotenv()

app = typer.Typer(help="Muninn (memoria/agenda) e Huginn (busca web).")
huginn_app = typer.Typer(help="Corvo do pensamento - busca web e memoria.")
console = Console()


async def _huginn_chat_loop() -> None:
    console.print("\n[bold magenta]Huginn[/bold magenta] | corvo do pensamento")
    console.print("[dim]Digite 'sair' para encerrar. Consulta em texto livre.[/dim]\n")
    while True:
        try:
            user_input = Prompt.ask("[bold green]Consulta[/bold green]")
        except (KeyboardInterrupt, EOFError):
            break
        if user_input.lower().strip() == "sair":
            break
        if not user_input.strip():
            continue
        with console.status("[dim]Buscando e resumindo...[/dim]"):
            summary = await run_huginn_query(user_input.strip(), save_to_memory=True)
        console.print("\n[bold magenta]Huginn[/bold magenta]")
        console.print(Markdown(summary))
        console.print()


@huginn_app.command("chat")
def huginn_chat() -> None:
    """REPL: pesquisa na web com resumo Huginn (grava resumo na memoria do Muninn)."""
    asyncio.run(_huginn_chat_loop())


@huginn_app.command("server")
def huginn_server(
    host: str = typer.Option("", "--host", help="Host do servidor Huginn"),
    port: int = typer.Option(0, "--port", help="Porta do servidor Huginn"),
) -> None:
    """Executa o servidor FastAPI do Huginn (webhooks + /task)."""
    try:
        import uvicorn
    except Exception as exc:
        raise RuntimeError("uvicorn nao instalado. Rode `pip install -r requirements.txt`.") from exc
    settings = get_settings()
    final_host = host.strip() or settings.huginn_host
    final_port = port if port > 0 else settings.huginn_port
    configure_logging(settings.log_dir)
    uvicorn.run(
        "huginn.server:app",
        host=final_host,
        port=final_port,
        reload=False,
        log_config=None,
    )


app.add_typer(muninn_app, name="muninn")
app.add_typer(huginn_app, name="huginn")


@app.command("chat")
def legacy_chat(
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="claude ou deepseek"),
    session: str = typer.Option(None, "--session", "-s", help="ID da sessao existente"),
    deepseek_mode: DeepseekMode = typer.Option(
        DeepseekMode.chat,
        "--deepseek-mode",
        help="chat ou reasoner (apenas DeepSeek)",
    ),
):
    """Alias para `muninn chat` (compativel com versoes anteriores)."""
    run_muninn_chat(model, session, deepseek_mode)


@app.command("memory")
def legacy_memory(
    action: str = typer.Argument(..., help="list | search"),
    query: str = typer.Argument("", help="Texto para busca"),
    type_filter: str = typer.Option("", "--type", "-t", help="note | preference | result"),
):
    """Alias para `muninn memory`."""
    run_muninn_memory(action, query, type_filter)


if __name__ == "__main__":
    app()
