# Muninn

Assistente pessoal com **memória persistente**, histórico de conversas e integração com **Google Calendar** e **Google Tasks**, exposto como servidor **MCP** (Model Context Protocol). O **Huginn** faz buscas na web, pode resumir resultados com DeepSeek e grava/consulta a mesma memória do Muninn — no **Telegram** (bot) ou no **terminal** (subcomando do CLI).

Na mitologia nórdica, Muninn e Huginn são os corvos de Odin — *memória* e *pensamento*. Aqui, Muninn centraliza contexto e agenda; Huginn traz informação do mundo exterior.

## O que a aplicação faz

| Componente | Função |
|------------|--------|
| **`cli.py`** | Interface de linha de comando raiz: subcomandos **`muninn`** (chat e memórias) e **`huginn`** (REPL de busca web); mantém aliases **`chat`** e **`memory`** para compatibilidade. |
| **`muninn.py`** | Lógica do assistente Muninn: prompt de sistema, Claude/DeepSeek, loop de conversa, ferramentas via subprocesso MCP, comando `memory`. |
| **`huginn_pipeline.py`** | Pipeline compartilhado de Huginn: tradução da query, busca (DuckDuckGo), resumo DeepSeek, gravação opcional na memória via MCP. Usado pelo CLI e pelo bot Telegram. |
| **`mcp_server.py`** | Servidor MCP em **stdio** (JSON-RPC linha a linha): memórias e conversas no Supabase; ferramentas de calendário e tarefas quando o Google está configurado. |
| **`huginn.py`** | Bot Telegram: palavra-chave configurável dispara busca web; `/memoria` consulta memórias; resumos podem ser salvos no Muninn. |
| **`ravens_gui.py`** | GUI nativa (CustomTkinter, tema dark) para operar Muninn/Huginn com output em tempo real e envio de stdin para modos interativos. |
| **`launch_ravens.bat`** | Launcher Windows: valida projeto/venv, instala `customtkinter` se ausente e abre a GUI com `pythonw.exe` (sem console). |
| **`setup_desktop.bat`** | Script Windows para criar/atualizar atalho `.lnk` na área de trabalho apontando para `launch_ravens.bat`. |

## Requisitos

- Python 3.10+ (recomendado)
- Conta e projeto no [Supabase](https://supabase.com) com tabelas compatíveis (`conversations`, `memories`, `events`, etc., conforme o código do servidor)
- Chaves de API conforme o modelo escolhido (Anthropic e/ou DeepSeek)
- Para o Huginn no Telegram: bot criado no [@BotFather](https://t.me/BotFather)
- Para Calendar/Tasks no MCP: fluxo OAuth Google (`credentials.json` / `token.json` — ver `google_auth.py`)

## Instalação

```powershell
cd caminho\para\muninn
python -m venv .venv
.\.venv\Scripts\Activate.ps1
& "C:\Users\klaus\Projects\Forja de Artigos Acadêmicos\.venv\Scripts\Activate.ps1" (powershell)
pip install -r requirements.txt
```

Crie um arquivo **`.env`** na raiz do repositório (mesmo nível que `cli.py` e `muninn.py`). Exemplo mínimo — ajuste aos componentes que for usar:

```env
# Supabase (obrigatório para mcp_server e memória no CLI/Huginn)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=sua_service_role_ou_anon_key

# Muninn CLI — chat (pelo menos uma chave, conforme o modelo)
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
DEFAULT_MODEL=deepseek

# Huginn (Telegram e/ou pipeline no CLI — tradução e resumo)
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat

# Huginn (somente Telegram)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=123456789
HUGINN_AUTH_KEYWORD=corvo

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

### CLI (`cli.py` / `muninn.py`)

| Variável | Uso |
|----------|-----|
| `ANTHROPIC_API_KEY` | Modelo Claude (tools completas via MCP) |
| `DEEPSEEK_API_KEY` | Modelo DeepSeek (sem tool-calling nativo no fluxo atual) |
| `DEFAULT_MODEL` | Padrão: `deepseek` ou `claude` (via `--model` / `-m`) |

### Servidor MCP (`mcp_server.py`)

Mesmas variáveis Supabase. Para **Google Calendar / Tasks**, o código usa `google_tools` e `google_auth.py`: coloque `credentials.json` na raiz do projeto e complete o fluxo OAuth na primeira execução que solicitar token. Variáveis como `GOOGLE_MUNINN_EMAIL` e `GOOGLE_PERSONAL_EMAIL` aparecem no servidor ao criar eventos.

### Huginn (Telegram — `huginn.py`; pipeline no terminal — `huginn_pipeline.py`)

| Variável | Obrigatória (Telegram) | Uso |
|----------|------------------------|-----|
| `TELEGRAM_BOT_TOKEN` | Sim | Token do bot |
| `TELEGRAM_ALLOWED_CHAT_ID` | Sim | ID numérico do chat autorizado (apenas esse chat é atendido) |
| `HUGINN_AUTH_KEYWORD` | Sim | Prefixo em minúsculas; mensagens `keyword ...` disparam a busca no Telegram |
| `DEEPSEEK_API_KEY` | Não | Tradução da query e resumo dos resultados (Telegram e CLI) |
| `DEEPSEEK_MODEL` | Não | Padrão `deepseek-chat` (resumos e tradução no pipeline Huginn) |

No **CLI**, o comando `huginn chat` não usa Telegram: basta consulta em texto livre. A palavra-chave `HUGINN_AUTH_KEYWORD` aplica-se apenas ao bot.

Para `/memoria`, gravação após pesquisa e o REPL `huginn chat`, o código chama o `mcp_server.py` em subprocesso — é necessário **Supabase** válido no mesmo `.env`.

## Como executar

Sempre com o venv ativado e dependências instaladas, na pasta do projeto.

### Interface de linha de comando

O ponto de entrada principal continua sendo `cli.py`. Subcomandos explícitos:

```powershell
python cli.py --help
python cli.py muninn chat
python cli.py muninn chat --model claude
python cli.py muninn chat --model deepseek --deepseek-mode reasoner
python cli.py muninn chat --session <uuid-sessao>
python cli.py muninn memory list
python cli.py muninn memory search "texto"
python cli.py muninn memory list --type note
```

**Aliases** (equivalentes ao `muninn` acima, para compatibilidade com versões anteriores):

```powershell
python cli.py chat
python cli.py chat --deepseek-mode reasoner
python cli.py memory list
python cli.py memory search "texto"
```

**Huginn no terminal** (busca web + resumo; grava resumo na memória do Muninn quando possível):

```powershell
python cli.py huginn chat
```

**Huginn server (FastAPI)**:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
python cli.py huginn server
```

Quando `BROWSER_TOOLS=true`, o startup do servidor valida Playwright/Chromium.
Se o Chromium nao estiver instalado, o servidor falha de forma explicita.
Correcao:

```powershell
.\.venv\Scripts\Activate.ps1
playwright install chromium
```

Leitura correta do arquivo de log no PowerShell:

```powershell
Get-Content .\logs\huginn.log -Encoding UTF8 -Wait -Tail 50
```

Também pode executar o módulo Muninn diretamente:

```powershell
python muninn.py chat --help
python muninn.py memory list
```

O comando `muninn chat` inicia o loop de conversa; o modelo **Claude** usa o servidor MCP para memória, conversas, calendário e tarefas. Com **DeepSeek**, use `--deepseek-mode chat` (padrão, `deepseek-chat`) ou `--deepseek-mode reasoner` (`deepseek-reasoner`) para tarefas mais exigentes; com `--model claude`, o modo reasoner é ignorado (apenas DeepSeek).

### GUI Windows (Ravens Control Panel)

A GUI desktop fica na raiz do projeto:

- `ravens_gui.py`
- `launch_ravens.bat`
- `setup_desktop.bat`

Fluxo recomendado no Windows:

```powershell
cd caminho\para\muninn
setup_desktop.bat
```

Isso cria/atualiza o atalho `Ravens Control Panel` na area de trabalho.
Use o atalho para abrir a GUI sem janela de terminal.

Na primeira execucao, `launch_ravens.bat` valida o `.venv` local e instala
`customtkinter` automaticamente se necessario.

Recursos da GUI:

- Seleciona Muninn/Huginn e comando alvo.
- Configura argumentos dinamicos antes de executar.
- Exibe output em tempo real.
- Envia stdin para modos interativos (`muninn chat`, `huginn chat`, `mcp server`).
- Persiste historico em `.ravens_history.json` com reexecucao por clique.

Observacao: o historico salva um trecho de output (ultimos 2000 caracteres)
por execucao para consulta rapida.

#### Implementações desta sessão (GUI + launcher)

- `ravens_gui.py` com layout em dois painéis (controles + output), tema dark e execução de comandos Muninn/Huginn.
- Execução de subprocesso não bloqueante com `thread + queue`, exibindo stdout em tempo real na interface.
- `stdin forwarding` para modos interativos (`muninn chat`, `huginn chat`, `mcp server`) pela caixa "Send".
- Histórico persistente em `.ravens_history.json` com timestamp, bot, comando, argumentos, `exit_code` e snippet de output.
- Clique no histórico para reexecutar; se já houver processo rodando, a GUI pede confirmação antes de trocar.
- `launch_ravens.bat` autodetecta a pasta do projeto pelo local do próprio `.bat` (sem `PROJECT_DIR` manual).
- `setup_desktop.bat` cria/atualiza o atalho de desktop de forma idempotente.
- `.ravens_history.json` foi adicionado ao `.gitignore`.

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

Este modo usa **stdio**: não há menu interativo. É o formato esperado quando um cliente MCP (por exemplo `muninn.py`, `cli.py` ou `muninn_bridge.py` usado pelo pipeline Huginn) inicia o processo e envia JSON-RPC. Rodar manualmente serve sobretudo para depuração ou integração com outro cliente MCP.

Em uso normal, **não é obrigatório** abrir um terminal só para o `mcp_server.py`: o CLI e o Huginn já o disparam quando precisam das ferramentas.

## Estrutura relevante

| Arquivo | Papel |
|---------|--------|
| `cli.py` | Typer raiz: `muninn`, `huginn`, aliases `chat` / `memory` |
| `muninn.py` | Muninn: prompt, providers, loop de chat, MCP, `memory` |
| `huginn_pipeline.py` | Pipeline Huginn (web + DeepSeek + memória) |
| `mcp_server.py` | Implementação MCP + Supabase (+ Google nas tools) |
| `huginn.py` | Aplicação `python-telegram-bot` |
| `huginn_tools.py` | Busca web (ex.: DuckDuckGo) e formatação |
| `muninn_bridge.py` | Cliente MCP usado pelo pipeline Huginn para memória |
| `google_auth.py` / `google_tools.py` | OAuth e operações Google |
| `ravens_gui.py` | GUI desktop para operação de Muninn/Huginn |
| `launch_ravens.bat` | Inicializa GUI no Windows sem console |
| `setup_desktop.bat` | Cria/atualiza atalho na área de trabalho |
| `.ravens_history.json` | Histórico persistente da GUI (gerado automaticamente) |

## Segurança

- Não commite `.env`, `token.json` nem chaves.  
- O Huginn no Telegram restringe respostas ao `TELEGRAM_ALLOWED_CHAT_ID`; confira o ID antes de expor o bot.  
- Revise políticas RLS no Supabase conforme o nível de exposição da `SUPABASE_KEY`.

## Licença

Não especificada neste repositório; adicione um ficheiro `LICENSE` se for distribuir o projeto.
