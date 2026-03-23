# Muninn

Assistente pessoal com **memória persistente**, histórico de conversas e integração com **Google Calendar** e **Google Tasks**, exposto como servidor **MCP** (Model Context Protocol). O **Huginn** é um bot no **Telegram** que faz buscas na web, pode resumir resultados com DeepSeek e grava/consulta a mesma memória do Muninn.

Na mitologia nórdica, Muninn e Huginn são os corvos de Odin — *memória* e *pensamento*. Aqui, Muninn centraliza contexto e agenda; Huginn traz informação do mundo exterior.

## O que a aplicação faz

| Componente | Função |
|------------|--------|
| **`cli.py`** | Interface de linha de comando: chat com o assistente (Claude ou DeepSeek), uso de ferramentas via subprocesso MCP, comandos para listar/buscar memórias. |
| **`mcp_server.py`** | Servidor MCP em **stdio** (JSON-RPC linha a linha): memórias e conversas no Supabase; ferramentas de calendário e tarefas quando o Google está configurado. |
| **`huginn.py`** | Bot Telegram: palavra-chave configurável dispara busca web; `/memoria` consulta memórias; resumos podem ser salvos no Muninn. |

## Requisitos

- Python 3.10+ (recomendado)
- Conta e projeto no [Supabase](https://supabase.com) com tabelas compatíveis (`conversations`, `memories`, `events`, etc., conforme o código do servidor)
- Chaves de API conforme o modelo escolhido (Anthropic e/ou DeepSeek)
- Para o Huginn: bot criado no [@BotFather](https://t.me/BotFather)
- Para Calendar/Tasks no MCP: fluxo OAuth Google (`credentials.json` / `token.json` — ver `google_auth.py`)

## Instalação

```powershell
cd caminho\para\muninn
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crie um arquivo **`.env`** na raiz do repositório (mesmo nível que `cli.py`). Exemplo mínimo — ajuste aos componentes que for usar:

```env
# Supabase (obrigatório para mcp_server e memória no CLI/Huginn)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=sua_service_role_ou_anon_key

# CLI — chat (pelo menos uma, conforme o modelo)
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
DEFAULT_MODEL=deepseek

# Huginn (Telegram)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=123456789
HUGINN_AUTH_KEYWORD=corvo
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat

# Google (opcional — usado pelas tools de calendário/tarefas no MCP)
GOOGLE_MUNINN_EMAIL=
GOOGLE_PERSONAL_EMAIL=
```

## Variáveis de ambiente (referência)

### Supabase

| Variável | Uso |
|----------|-----|
| `SUPABASE_URL` | URL do projeto |
| `SUPABASE_KEY` | Chave de API (anon ou service role, conforme sua política RLS) |

### CLI (`cli.py`)

| Variável | Uso |
|----------|-----|
| `ANTHROPIC_API_KEY` | Modelo Claude (tools completas via MCP) |
| `DEEPSEEK_API_KEY` | Modelo DeepSeek (sem tool-calling nativo no fluxo atual) |
| `DEFAULT_MODEL` | Padrão: `deepseek` ou `claude` (via `--model` / `-m`) |

### Servidor MCP (`mcp_server.py`)

Mesmas variáveis Supabase. Para **Google Calendar / Tasks**, o código usa `google_tools` e `google_auth.py`: coloque `credentials.json` na raiz do projeto e complete o fluxo OAuth na primeira execução que solicitar token. Variáveis como `GOOGLE_MUNINN_EMAIL` e `GOOGLE_PERSONAL_EMAIL` aparecem no servidor ao criar eventos.

### Huginn (`huginn.py`)

| Variável | Obrigatória | Uso |
|----------|-------------|-----|
| `TELEGRAM_BOT_TOKEN` | Sim | Token do bot |
| `TELEGRAM_ALLOWED_CHAT_ID` | Sim | ID numérico do chat autorizado (apenas esse chat é atendido) |
| `HUGINN_AUTH_KEYWORD` | Sim | Prefixo em minúsculas; mensagens `keyword ...` disparam a busca |
| `DEEPSEEK_API_KEY` | Não | Tradução da query e resumo dos resultados |
| `DEEPSEEK_MODEL` | Não | Padrão `deepseek-chat` |

Para `/memoria` e gravação após pesquisa, o Huginn chama o `mcp_server.py` em subprocesso — é necessário **Supabase** válido no mesmo `.env`.

## Como executar

Sempre com o venv ativado e dependências instaladas, na pasta do projeto.

### Interface de linha de comando (Muninn)

```powershell
python cli.py --help
python cli.py chat
python cli.py chat --model claude
python cli.py chat --session <uuid-sessao>
python cli.py memory list
python cli.py memory search "texto"
python cli.py memory list --type note
```

O comando `chat` inicia o loop de conversa; o modelo Claude usa o servidor MCP para memória, conversas, calendário e tarefas.

### Bot Telegram (Huginn)

```powershell
python huginn.py
```

Deixe o processo em execução (polling). Interrompa com **Ctrl+C**.

- `/start` — mensagem de boas-vindas  
- `/memoria` — lista memórias via Muninn  
- `<HUGINN_AUTH_KEYWORD> sua pergunta` — busca web, resumo opcional com DeepSeek, tentativa de salvar resumo na memória  

### Servidor MCP isolado

```powershell
python mcp_server.py
```

Este modo usa **stdio**: não há menu interativo. É o formato esperado quando um cliente MCP (por exemplo o `cli.py` ou `muninn_bridge.py` usado pelo Huginn) inicia o processo e envia JSON-RPC. Rodar manualmente serve sobretudo para depuração ou integração com outro cliente MCP.

Em uso normal, **não é obrigatório** abrir um terminal só para o `mcp_server.py`: o CLI e o Huginn já o disparam quando precisam das ferramentas.

## Estrutura relevante

| Arquivo | Papel |
|---------|--------|
| `cli.py` | Typer + Rich; orquestra chat e chama MCP |
| `mcp_server.py` | Implementação MCP + Supabase (+ Google nas tools) |
| `huginn.py` | Aplicação `python-telegram-bot` |
| `huginn_tools.py` | Busca web (ex.: DuckDuckGo) e formatação |
| `muninn_bridge.py` | Cliente MCP usado pelo Huginn para memória |
| `google_auth.py` / `google_tools.py` | OAuth e operações Google |

## Segurança

- Não commite `.env`, `token.json` nem chaves.  
- O Huginn restringe respostas ao `TELEGRAM_ALLOWED_CHAT_ID`; confira o ID antes de expor o bot.  
- Revise políticas RLS no Supabase conforme o nível de exposição da `SUPABASE_KEY`.

## Licença

Não especificada neste repositório; adicione um ficheiro `LICENSE` se for distribuir o projeto.
