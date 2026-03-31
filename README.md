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

Também pode executar o módulo Muninn diretamente:

```powershell
python muninn.py chat --help
python muninn.py memory list
```

O comando `muninn chat` inicia o loop de conversa; o modelo **Claude** usa o servidor MCP para memória, conversas, calendário e tarefas. Com **DeepSeek**, use `--deepseek-mode chat` (padrão, `deepseek-chat`) ou `--deepseek-mode reasoner` (`deepseek-reasoner`) para tarefas mais exigentes; com `--model claude`, o modo reasoner é ignorado (apenas DeepSeek).

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

## Boas práticas e debug (hardening)

Esta seção resume os cuidados recomendados após o hardening recente (adapter MCP compartilhado, tratamento de erros e testes).

### 1) Fluxo de qualidade recomendado

Rode localmente os mesmos checks da CI:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt ruff
ruff check . --select E9,F63,F7,F82
python -m unittest discover -s tests -p "test_*.py" -v
```

### 2) Boas práticas de manutenção

- Mantenha chamadas MCP passando sempre pelo adapter (`mcp_client.py`), evitando duplicar subprocesso/handshake em outros módulos.
- Preserve o contrato atual de resiliência no app (`call_mcp_tool`/`call_muninn`): falha de MCP não derruba o chat, mas deve gerar log com contexto.
- Evite `except Exception` em parsing local (JSON/estrutura). Prefira exceções específicas (`json.JSONDecodeError`, `TypeError`, `KeyError`, etc.).
- Em boundaries externos (rede/API), fallback é permitido, mas com logging explícito.
- Ao alterar `google_tools.py`, mantenha API pública estável (`create_event`, `list_events`, `delete_event`, `update_event`, `create_task`, `list_tasks`).

### 3) Novos códigos de erro MCP (internos)

O adapter `mcp_client.py` padroniza falhas em exceções tipadas:

- `McpClientTimeoutError`: timeout aguardando resposta do processo MCP.
- `McpClientProtocolError`: resposta MCP malformada/inválida.
- `McpClientProcessError`: processo MCP finalizou com erro antes de retorno válido.

No `muninn.py` e `muninn_bridge.py`, essas falhas são capturadas para manter compatibilidade de runtime (retorno vazio + log).

### 4) Playbook rápido de debug

1. **Falha em memória/eventos/tarefas no chat**  
   - Verifique `.env` (`SUPABASE_URL`, `SUPABASE_KEY`, chaves Google).  
   - Teste o servidor MCP isolado:
   ```powershell
   python mcp_server.py
   ```
2. **Saída vazia em tool call do Muninn/Huginn**  
   - Rode os testes de MCP:
   ```powershell
   python -m unittest tests/test_mcp_client.py -v
   ```
   - Revise logs de erro em `muninn.py`/`muninn_bridge.py` para identificar se foi timeout, protocolo ou processo.
3. **Regressão em integração Google**  
   - Rode testes focados:
   ```powershell
   python -m unittest tests/test_google_tools.py -v
   ```
4. **Regressão no parser/fallback do Muninn**  
   - Rode:
   ```powershell
   python -m unittest tests/test_muninn.py -v
   ```

### 5) CI

A pipeline mínima está em `.github/workflows/ci.yml` e executa:

- lint crítico com `ruff` (`E9`, `F63`, `F7`, `F82`);
- suíte `unittest` em `tests/`.

## Segurança

- Não commite `.env`, `token.json` nem chaves.  
- O Huginn no Telegram restringe respostas ao `TELEGRAM_ALLOWED_CHAT_ID`; confira o ID antes de expor o bot.  
- Revise políticas RLS no Supabase conforme o nível de exposição da `SUPABASE_KEY`.

## Licença

Não especificada neste repositório; adicione um ficheiro `LICENSE` se for distribuir o projeto.
