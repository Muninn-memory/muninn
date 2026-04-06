# Huginn — Arquitetura & Roadmap de Evolução

> Huginn é o corvo do pensamento. Na nova arquitetura, evolui de bot Telegram para um **agente autônomo multi-plataforma** com orquestração LLM, browser agent de navegação humana, memória persistente via Muninn e logging de custo por sessão.

---

## Índice

1. [Estado Atual](#1-estado-atual)
2. [Estado Alvo — Visão Completa](#2-estado-alvo--visão-completa)
3. [Estrutura de Arquivos](#3-estrutura-de-arquivos)
4. [Pipeline Completo](#4-pipeline-completo)
5. [Fluxo de Execução Detalhado](#5-fluxo-de-execução-detalhado)
6. [Modos de Operação](#6-modos-de-operação)
7. [Ferramentas do Agente](#7-ferramentas-do-agente)
8. [Canais de Comunicação](#8-canais-de-comunicação)
9. [Roadmap de Implementação](#9-roadmap-de-implementação)
10. [Implantação — Docker](#10-implantação--docker)
11. [Implantação — Desenvolvimento Local (Windows)](#11-implantação--desenvolvimento-local-windows)
12. [Variáveis de Ambiente](#12-variáveis-de-ambiente)

---

## 1. Estado Atual

O Huginn atual (`huginn.py`) é um bot Telegram com pipeline linear:

```
Telegram → huginn.py → huginn_pipeline.py
                           ├── translate_query()     (DeepSeek-chat)
                           ├── web_search()          (DuckDuckGo via ddgs)
                           └── summarize()           (DeepSeek-chat)
                                    │
                                    └── muninn_bridge.py → mcp_server.py → Supabase
```

**Limitações do estado atual:**

- Canal único (Telegram)
- Pipeline flat sem orquestração — cada mensagem segue o mesmo caminho fixo
- Sem capacidade de navegar na web como agente
- Sem loop de raciocínio — uma chamada LLM por mensagem
- Sem logging de custo ou uso de tokens
- DeepSeek é o único modelo; sem escolha dinâmica de modelo por complexidade

---

## 2. Estado Alvo — Visão Completa

```
                    ┌─────────────────────────────────────────┐
                    │           RAVENS SYSTEM                  │
                    │                                         │
      ┌─────────┐   │  ┌──────────────────────────────────┐  │
      │ravens_  │───┼─▶│       huginn/server.py           │  │
      │gui.py   │   │  │   FastAPI — webhooks + /task     │  │
      └─────────┘   │  └────────────────┬─────────────────┘  │
                    │                   │                     │
      ┌─────────┐   │                   ▼                     │
      │Telegram │───┼─▶  ┌─────────────────────────────┐     │
      └─────────┘   │    │    huginn/agent.py           │     │
                    │    │                              │     │
      ┌─────────┐   │    │  FASE 1: BOOST (opcional)   │     │
      │WhatsApp │───┼─▶  │  FASE 2: AGENT LOOP         │     │
      │  Web    │   │    │  FASE 3: VALIDAÇÃO           │     │
      └─────────┘   │    │  FASE 4: LOG                 │     │
                    │    └──────────────┬──────────────┘     │
      ┌─────────┐   │                   │                     │
      │Instagram│───┼─▶           tools/│providers/           │
      │  Web    │   │    ┌──────────────┼──────────────┐      │
      └─────────┘   │    │              │              │      │
                    │    ▼              ▼              ▼      │
                    │ web_search   browser.py     memory.py  │
                    │ (DuckDuckGo) (Playwright)  (Muninn MCP)│
                    │                                         │
                    │   providers/                            │
                    │   claude.py + deepseek.py + factory.py │
                    │                                         │
                    │   logger.py → logs/sessions.csv + .db  │
                    └─────────────────────────────────────────┘
```

---

## 3. Estrutura de Arquivos

### Estado atual (referência)

```
muninn/
├── huginn.py               ← bot Telegram (será substituído)
├── huginn_pipeline.py      ← pipeline flat (será absorvido)
├── huginn_tools.py         ← DuckDuckGo (será movido)
├── muninn_bridge.py        ← bridge MCP (será expandido)
├── muninn.py               ← inalterado (memória, calendar, LLM Muninn)
├── mcp_server.py           ← inalterado (MCP stdio + Supabase)
├── mcp_client.py           ← inalterado
├── google_tools.py         ← inalterado
├── ravens_gui.py           ← receberá aba Dispatch (Fase 8)
└── cli.py                  ← inalterado
```

### Estado alvo (completo)

```
muninn/
│
├── huginn/
│   ├── __init__.py
│   │
│   ├── soul.py                  ← prompts: HUGINN_SYSTEM, PLANNER_SYSTEM,
│   │                                        VALIDATOR_SYSTEM, deep_think templates
│   ├── config.py                ← HUGINN_MODE, chaves por papel, pricing,
│   │                                feature flags (boost, validate, browser, logging)
│   ├── agent.py                 ← ponto de entrada: run(task, session_id, channel)
│   │                                fases: boost → loop → validate → log
│   ├── logger.py                ← TokenUsage, save_usage(), session_report(),
│   │                                cost_summary() → logs/sessions.csv + .db
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              ← LLMProvider ABC, LLMResponse, TokenUsage dataclass
│   │   ├── claude.py            ← Claude Sonnet (orch) + Opus (boost/validate)
│   │   ├── deepseek.py          ← DeepSeek-chat (exec) + reasoner (deep_think)
│   │   └── factory.py           ← get_provider(role=...) mode-aware
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py          ← TOOLS dict + execute_tool(name, args)
│   │   ├── web_search.py        ← DuckDuckGo (huginn_tools.py → aqui)
│   │   ├── browser.py           ← Playwright efêmero para tasks (Manus-like)
│   │   ├── memory.py            ← recall_memory, save_memory, search_memory
│   │   │                           via muninn_bridge / MCP
│   │   ├── calendar.py          ← check_calendar, create_event via MCP
│   │   └── deep_think.py        ← escalona para DeepSeek-reasoner e retorna
│   │
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py              ← HuginnMessage dataclass, ChannelAdapter ABC
│   │   ├── browser_base.py      ← SessionBrowser: login, cookie persistence,
│   │   │                           poll loop, send — base para WA e IG
│   │   ├── telegram.py          ← python-telegram-bot, polling nativo
│   │   ├── whatsapp.py          ← Playwright session no WhatsApp Web
│   │   └── instagram.py         ← Playwright session no Instagram Web
│   │
│   └── server.py                ← FastAPI: webhooks (TG/WA/IG) + POST /task
│                                    (GUI dispatch) + GET /status
│
├── logs/                        ← gerado automaticamente
│   ├── sessions.csv
│   └── sessions.db
│
├── prompts/                     ← opcional: versionar prompts separados do código
│   ├── huginn_system.md
│   ├── planner_system.md
│   └── validator_system.md
│
├── muninn.py                    ← inalterado
├── mcp_server.py                ← inalterado
├── mcp_client.py                ← inalterado
├── muninn_bridge.py             ← inalterado (usado por huginn/tools/memory.py)
├── google_tools.py              ← inalterado
├── ravens_gui.py                ← +aba Dispatch (Fase 8)
├── cli.py                       ← inalterado
└── docker-compose.yml           ← atualizado: huginn roda server.py
```

---

## 4. Pipeline Completo

### Pipeline atual (flat)

```
[mensagem Telegram]
       │
       ▼
huginn.py — handle_message()
       │
       ├─ /start, /memoria  →  resposta direta via muninn_bridge
       │
       └─ <keyword> <query>
               │
               ▼
       huginn_pipeline.run_huginn_query()
               ├── 1. translate_query()     DeepSeek-chat
               ├── 2. web_search()          DuckDuckGo
               ├── 3. summarize()           DeepSeek-chat
               └── 4. save_to_memory()      Muninn MCP (opcional)
                          │
                          ▼
               [resposta ao Telegram]
```

### Pipeline alvo (agente completo)

```
[mensagem: Telegram / WhatsApp / Instagram / GUI]
       │
       ▼
huginn/server.py
  └── channel adapter normaliza → HuginnMessage(channel, sender, text, meta)
       │
       ▼
huginn/agent.py — run(task, session_id, channel)
       │
       ├─── FASE 1: BOOST (se LLM_BOOST_ENABLED=true)
       │     └── Claude Opus / Sonnet
       │           recebe: task bruta
       │           retorna: plano estruturado JSON
       │                    (subtarefas, ferramentas sugeridas, contexto)
       │           task enriquecida → próxima fase
       │
       ├─── FASE 2: AGENT LOOP (core)
       │     └── Orquestrador (Claude Sonnet ou DeepSeek-chat, por HUGINN_MODE)
       │           ┌─────────────────────────────────────────────┐
       │           │  while iter < MAX_ITERATIONS:               │
       │           │    response = orchestrator.complete(msgs)   │
       │           │                                             │
       │           │    if response == __DONE__: break           │
       │           │                                             │
       │           │    for tool_call in response.tool_calls:    │
       │           │      result = execute_tool(name, args)      │
       │           │      msgs.append(tool_result)               │
       │           └─────────────────────────────────────────────┘
       │
       │     Tools disponíveis no loop:
       │       ├── web_search(query)          → DuckDuckGo + resumo
       │       ├── browser_navigate(task)     → Playwright efêmero
       │       ├── recall_memory(query)       → Muninn MCP
       │       ├── save_memory(title,content) → Muninn MCP
       │       ├── check_calendar(period)     → Google Calendar MCP
       │       ├── send_message(channel,text) → resposta no canal de origem
       │       ├── deep_think(question)       → DeepSeek-reasoner on demand
       │       └── spawn_subagent(task)       → [STUB — Fase 2 do roadmap]
       │
       ├─── FASE 3: VALIDAÇÃO (se LLM_VALIDATE_ENABLED=true)
       │     └── Claude Sonnet / Opus
       │           recebe: task original + resultado do loop
       │           retorna: APROVADO  →  resultado segue
       │                    REJEITAR: <motivo>  →  retry com contexto do erro
       │
       └─── FASE 4: LOG
             └── logger.py
                   ├── TokenUsage por fase (boost, loop, validate, deep_think)
                   ├── Custo estimado em USD por sessão
                   ├── logs/sessions.csv  (legível, uma linha por entrada)
                   └── logs/sessions.db   (SQLite, consultável)
```

---

## 5. Fluxo de Execução Detalhado

### Exemplo: "wodan pesquise os últimos lançamentos de smartphones e salva na memória"

```
1. [Telegram] mensagem recebida
       ↓
2. [server.py] webhook → HuginnMessage(
       channel="telegram",
       sender="5091577709",
       text="wodan pesquise os últimos lançamentos de smartphones e salva na memória"
   )
       ↓
3. [agent.py] session_id gerado → "a3f9c2b1"

4. [FASE 1 — BOOST] (se habilitado)
   Claude Sonnet recebe a task e retorna:
   {
     "plan_summary": "Pesquisa web + sumarização + gravação em memória",
     "steps": ["web_search", "save_memory"],
     "complexity": "low"
   }
       ↓
5. [FASE 2 — AGENT LOOP] Orquestrador (Claude Sonnet) começa

   Iteração 1:
     Claude decide → tool_call: web_search("latest smartphone releases 2025")
     huginn/tools/web_search.py → DuckDuckGo → 5 resultados
     DeepSeek-chat sumariza → texto formatado
     resultado injetado no contexto

   Iteração 2:
     Claude decide → tool_call: save_memory(
       title="Lançamentos smartphones 2025",
       content="<resumo>",
       tags=["tecnologia", "smartphones", "huginn"]
     )
     huginn/tools/memory.py → muninn_bridge → mcp_server → Supabase
     resultado: "Memória salva."

   Iteração 3:
     Claude decide → tool_call: send_message(
       channel="telegram",
       text="Pesquisa concluída e salva na memória, Mestre. [resumo]"
     )
     huginn/channels/telegram.py → reply_text()
     resultado: __DONE__: tarefa concluída
       ↓
6. [FASE 3 — VALIDAÇÃO] (se habilitado)
   Claude Sonnet recebe task + resultado → APROVADO
       ↓
7. [FASE 4 — LOG]
   TokenUsage registrado:
     session_id: a3f9c2b1
     loop_input_tokens: 1240
     loop_output_tokens: 380
     deep_think_tokens: 0
     cost_usd: ~$0.0048
   → logs/sessions.csv + logs/sessions.db
       ↓
8. [Fim] resposta já entregue no Telegram via send_message (iteração 3)
```

### Exemplo: "wodan acessa o mercadolivre e me diz o preço do iPhone 15"

```
FASE 2 — AGENT LOOP:

  Iteração 1:
    Claude decide → tool_call: deep_think(
      "Como navegar no Mercado Livre para encontrar preço de produto específico"
    )
    huginn/tools/deep_think.py → DeepSeek-reasoner
    retorna: plano de navegação detalhado

  Iteração 2:
    Claude decide → tool_call: browser_navigate(
      task="Acesse mercadolivre.com.br, pesquise iPhone 15, retorne o menor preço"
    )
    huginn/tools/browser.py → Playwright (efêmero, headless)
      → abre mercadolivre.com.br
      → digita "iPhone 15" na busca
      → extrai preços dos primeiros resultados
      → fecha browser
    retorna: "iPhone 15 a partir de R$ 4.299,00"

  Iteração 3:
    Claude decide → tool_call: send_message(channel="telegram", text="...")
    → __DONE__
```

---

## 6. Modos de Operação

Controlado pela variável `HUGINN_MODE` no `.env`:

| `HUGINN_MODE` | Orquestrador | Execução / deep_think | Boost / Validador |
|---|---|---|---|
| `deepseek_orchestrator` | DeepSeek-chat | DeepSeek-chat / reasoner | Claude Sonnet (opcional) |
| `claude_orchestrator` | Claude Sonnet | DeepSeek-chat / reasoner | Claude Opus (opcional) |

**Regra fixa:** sub-agentes (`spawn_subagent`, Fase 2 do roadmap) sempre usam DeepSeek-chat, independente do modo — para manter custo controlado.

**Critérios de seleção dinâmica no loop (definidos no `soul.py`):**

| Situação detectada pelo orquestrador | Ação |
|---|---|
| Pergunta factual, resumo, tradução | Responde direto, sem tool extra |
| Raciocínio multi-passo, análise complexa | `deep_think` → DeepSeek-reasoner |
| Navegação web necessária | `browser_navigate` → Playwright |
| Contexto pessoal ou histórico necessário | `recall_memory` → Muninn MCP |
| Tarefa isolada paralelizável | `spawn_subagent` → DeepSeek-chat (Fase 2) |

---

## 7. Ferramentas do Agente

| Tool | Arquivo | Descrição |
|---|---|---|
| `web_search` | `tools/web_search.py` | DuckDuckGo via `ddgs`, tradução + resumo DeepSeek |
| `browser_navigate` | `tools/browser.py` | Playwright efêmero + LLM para navegação autônoma |
| `recall_memory` | `tools/memory.py` | Busca semântica na memória via Muninn MCP |
| `save_memory` | `tools/memory.py` | Grava nota/preferência/resultado no Supabase |
| `check_calendar` | `tools/calendar.py` | Lista/cria eventos via Google Calendar MCP |
| `send_message` | via `channels/` | Envia resposta no canal de origem da mensagem |
| `deep_think` | `tools/deep_think.py` | Escalona para DeepSeek-reasoner e retorna resultado |
| `spawn_subagent` | `agent.py` | **[STUB]** Instancia sub-loop DeepSeek — Fase 2 |

---

## 8. Canais de Comunicação

### Telegram
- Mantém `python-telegram-bot` com polling nativo
- Não usa Playwright — é o canal mais estável e direto
- Webhook registrado no `server.py` ou polling standalone

### WhatsApp Web + Instagram Web
- Implementados via **Playwright com sessão persistente** — sem Meta API oficial
- Primeiro acesso: login manual (QR code no WhatsApp, credenciais no Instagram)
- Sessão salva em cookies/localStorage entre reinicializações
- Polling periódico para detectar novas mensagens recebidas
- Humanização: delays randomizados, movimentos de mouse simulados via `playwright-stealth`

```
huginn/channels/browser_base.py  ← SessionBrowser base
  ├── login()                    ← primeiro acesso ou re-auth
  ├── save_session()             ← persiste cookies
  ├── load_session()             ← restaura sessão salva
  ├── poll_messages()            ← detecta novas mensagens (loop)
  └── send(recipient, text)      ← envia mensagem

huginn/channels/whatsapp.py      ← extends SessionBrowser
  ├── URL: web.whatsapp.com
  ├── login: aguarda QR scan
  └── poll: MutationObserver via JS injection

huginn/channels/instagram.py     ← extends SessionBrowser
  ├── URL: instagram.com/direct/inbox
  ├── login: credenciais .env
  └── poll: request periódico ao inbox
```

**Riscos e mitigações:**

| Risco | Canal | Mitigação |
|---|---|---|
| Detecção de headless | WA / IG | `playwright-stealth` + Xvfb no Docker |
| Sessão expirada | WA (QR periódico) | Re-auth automático + alerta no Telegram |
| Rate limit / ban | WA / IG | Delay humano entre ações, randomização de timing |
| WA — uma sessão por número | WA | Uma instância por número, sem execução paralela |

---

## 9. Roadmap de Implementação

### Fase 1 — Infraestrutura de providers e configuração
**Arquivos:** `huginn/config.py`, `huginn/providers/` (base, claude, deepseek, factory), `huginn/logger.py`

O que entrega:
- Abstração de providers com `LLMProvider` ABC
- Seleção de modelo por papel (orchestrator, boost, exec, validator)
- `HUGINN_MODE` configurável via `.env`
- Logging de tokens + custo em CSV e SQLite

---

### Fase 2 — Soul (prompts)
**Arquivos:** `huginn/soul.py`

O que entrega:
- `HUGINN_SYSTEM`: identidade do Huginn como agente autônomo distinto do Muninn
- `PLANNER_SYSTEM`: instrução para fase de boost/planejamento
- `VALIDATOR_SYSTEM`: instrução para fase de validação
- Regras de seleção dinâmica de tool e modelo dentro do system prompt

---

### Fase 3 — Tools
**Arquivos:** `huginn/tools/` (registry, web_search, memory, calendar, deep_think)

O que entrega:
- `web_search`: `huginn_tools.py` atual migrado e integrado ao registry
- `memory`: `muninn_bridge.py` expandido com recall, save, search
- `calendar`: list e create via Muninn MCP
- `deep_think`: wrapper que chama DeepSeek-reasoner e retorna ao orquestrador
- `spawn_subagent`: **stub** que retorna `"subagents not yet implemented"`
- `registry.py`: dicionário central de tools + `execute_tool(name, args)`

---

### Fase 4 — Agent loop
**Arquivo:** `huginn/agent.py`

O que entrega:
- Loop completo: boost → execução → validação → log
- `AgentLoop` class com `run(task)` → itera tool calls até `__DONE__`
- Função `run(task, session_id, channel)` como ponto de entrada público
- Compatível com chamada direta (CLI/testes) e via `server.py`

---

### Fase 5 — Migração do canal Telegram
**Arquivos:** `huginn/channels/base.py`, `huginn/channels/telegram.py`, `huginn/server.py`

O que entrega:
- `HuginnMessage` dataclass normalizado
- Bot Telegram migrado para `channels/telegram.py` com todos os comandos atuais (`/start`, `/ajuda`, `/muninn`, `/agenda`, `/tarefas`, `/lembrar`, `/memoria`, `/status`)
- `server.py` FastAPI com endpoint `POST /task` (GUI dispatch) e webhook Telegram
- `huginn.py` original substituído — `docker-compose.yml` atualizado

---

### Fase 6 — Browser agent (tools/browser.py)
**Arquivo:** `huginn/tools/browser.py`

O que entrega:
- Playwright efêmero para tasks autônomas (Manus-like)
- LLM-driven: recebe task em linguagem natural, navega e retorna resultado
- Screenshot opcional para debug na GUI
- Headless configurável via `BROWSER_HEADLESS` no `.env`
- Integrado ao tool registry como `browser_navigate`

---

### Fase 7 — Canais WhatsApp e Instagram
**Arquivos:** `huginn/channels/browser_base.py`, `huginn/channels/whatsapp.py`, `huginn/channels/instagram.py`

O que entrega:
- `SessionBrowser` base com login, persistência de sessão e polling
- WhatsApp Web: login por QR code, polling via JS injection
- Instagram Web: login por credenciais, polling periódico no inbox
- `playwright-stealth` para anti-detecção
- Alerta automático no Telegram em caso de sessão expirada

---

### Fase 8 — GUI Dispatch
**Arquivo:** `ravens_gui.py` (nova aba)

O que entrega:
- Aba "Dispatch" na GUI Ravens
- Campo de texto para task
- Seleção de canal de destino (Telegram / WhatsApp / Instagram / interno)
- Botão "Enviar para Huginn" → `POST http://localhost:8000/task`
- Exibição da resposta em tempo real no painel de output existente

---

### Fase 9 — spawn_subagent (roadmap futuro)
**Arquivo:** `huginn/agent.py` (expansão)

O que entrega:
- `AgentLoop` refatorado para async (`asyncio`)
- `spawn_subagent(task, context)` instancia sub-loop DeepSeek-chat
- `asyncio.gather()` para execução paralela de múltiplos sub-agentes
- Proteção anti-recursão: sub-agentes recebem toolset sem `spawn_subagent`
- `MAX_SUBAGENTS` e `SUBAGENT_MAX_ITER` configuráveis no `.env`

---

## 10. Implantação — Docker

### Pré-requisitos

```bash
# Docker Desktop instalado e rodando
docker --version   # 24.x ou superior
docker compose version  # 2.x ou superior
```

### Configuração inicial

```bash
# 1. Clone o repositório
git clone https://github.com/Muninn-memory/muninn.git
cd muninn

# 2. Crie o .env (ver seção 12 para todas as variáveis)
cp .env.example .env
# edite .env com suas chaves

# 3. Coloque credentials.json e token.json na raiz
# (Google OAuth — ver google_auth.py para gerar token.json)
```

### Build e execução

```bash
# Build completo
docker compose build

# Iniciar todos os serviços
docker compose up -d

# Verificar logs
docker compose logs -f huginn
docker compose logs -f muninn

# Parar tudo
docker compose down
```

### `docker-compose.yml` atualizado (estado alvo)

```yaml
services:
  muninn:
    build: .
    container_name: muninn
    stdin_open: true
    tty: true
    volumes:
      - ./.env:/app/.env:ro
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json:rw
    restart: unless-stopped

  huginn:
    build: .
    container_name: huginn
    command: uvicorn huginn.server:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    volumes:
      - ./.env:/app/.env:ro
      - ./credentials.json:/app/credentials.json:ro
      - ./token.json:/app/token.json:rw
      - ./logs:/app/logs
      - ./huginn_sessions:/app/huginn_sessions  # cookies WA/IG
    environment:
      - DISPLAY=:99          # Xvfb para Playwright headed
      - PYTHONUTF8=1
    restart: unless-stopped
    depends_on:
      - muninn
```

### Playwright no Docker

```dockerfile
# Adicionar ao Dockerfile existente (após pip install):
RUN playwright install chromium
RUN playwright install-deps chromium

# Para modo headed (VNC opcional):
RUN apt-get install -y xvfb
```

### Expor webhook para WhatsApp/Instagram (desenvolvimento)

```bash
# Opção 1: ngrok
ngrok http 8000
# Copie a URL https://xxxx.ngrok.io → HUGINN_WEBHOOK_BASE no .env

# Opção 2: Cloudflare Tunnel (persistente, gratuito)
cloudflared tunnel --url http://localhost:8000
```

---

## 11. Implantação — Desenvolvimento Local (Windows)

### Pré-requisitos

```powershell
python --version   # 3.10 ou superior
```

### Setup inicial

```powershell
# Na pasta do projeto
cd C:\Users\klaus\Projects\muninn

# Criar e ativar venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt

# Instalar Playwright e browsers
playwright install chromium
```

### Executar em desenvolvimento

```powershell
# Huginn como servidor FastAPI (nova arquitetura)
python -m uvicorn huginn.server:app --host 0.0.0.0 --port 8000 --reload

# Huginn apenas Telegram (sem FastAPI, para testes rápidos)
python -m huginn.channels.telegram

# Muninn CLI (inalterado)
python cli.py muninn chat --model deepseek

# GUI Ravens (inalterado)
launch_ravens.bat
```

### Executar agent diretamente (debug)

```powershell
# Testar o agent loop sem canal
python -c "
from huginn.agent import run
result = run('pesquise notícias de IA hoje')
print(result)
"

# Verificar custos de sessões
python -c "
from huginn.logger import cost_summary
print(cost_summary(days=7))
"

# Query direta no SQLite de logs
python -c "
import sqlite3
conn = sqlite3.connect('./logs/sessions.db')
rows = conn.execute('''
    SELECT mode, SUM(cost_usd) as total, COUNT(DISTINCT session_id) as sessions
    FROM sessions GROUP BY mode ORDER BY total DESC
''').fetchall()
for r in rows: print(r)
"
```

### `requirements.txt` atualizado (estado alvo)

```
# Existentes
anthropic
mcp
supabase
python-dotenv
typer
rich
openai
google-auth
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
python-dateutil
ddgs
python-telegram-bot

# Novos (Fase 1+)
fastapi
uvicorn[standard]
httpx

# Novos (Fase 6+)
playwright
browser-use
playwright-stealth
```

---

## 12. Variáveis de Ambiente

### `.env.example` completo (estado alvo)

```env
# ════════════════════════════════════════════
# SUPABASE (Muninn — inalterado)
# ════════════════════════════════════════════
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=

# ════════════════════════════════════════════
# MODO DO AGENTE HUGINN
# ════════════════════════════════════════════
# Opções: deepseek_orchestrator | claude_orchestrator
HUGINN_MODE=claude_orchestrator

# ════════════════════════════════════════════
# CHAVES POR PAPEL
# ════════════════════════════════════════════
# DeepSeek
DEEPSEEK_API_KEY=                        # fallback geral
DEEPSEEK_API_KEY_EXEC=                   # execução / sub-agentes
DEEPSEEK_API_KEY_REASON=                 # deep_think (reasoner)
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL_EXEC=deepseek-chat
DEEPSEEK_MODEL_REASON=deepseek-reasoner

# Anthropic
ANTHROPIC_API_KEY=                       # fallback geral
ANTHROPIC_API_KEY_ORCH=                  # Claude como orquestrador
ANTHROPIC_API_KEY_BOOST=                 # Claude como boost/validador
CLAUDE_MODEL_ORCH=claude-sonnet-4-6
CLAUDE_MODEL_BOOST=claude-opus-4-6

# ════════════════════════════════════════════
# FEATURES
# ════════════════════════════════════════════
LLM_BOOST_ENABLED=false
LLM_VALIDATE_ENABLED=false
MAX_ITERATIONS=30
EXEC_TIMEOUT=30

# ════════════════════════════════════════════
# BROWSER
# ════════════════════════════════════════════
BROWSER_TOOLS=true
BROWSER_HEADLESS=true

# ════════════════════════════════════════════
# CANAIS
# ════════════════════════════════════════════
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_ID=
HUGINN_AUTH_KEYWORD=wodan

# WhatsApp Web (Playwright session)
WHATSAPP_ENABLED=false
WHATSAPP_SESSION_DIR=./huginn_sessions/whatsapp

# Instagram Web (Playwright session)
INSTAGRAM_ENABLED=false
INSTAGRAM_USERNAME=
INSTAGRAM_PASSWORD=
INSTAGRAM_SESSION_DIR=./huginn_sessions/instagram

# ════════════════════════════════════════════
# SERVIDOR
# ════════════════════════════════════════════
HUGINN_HOST=0.0.0.0
HUGINN_PORT=8000
HUGINN_WEBHOOK_BASE=https://xxxx.ngrok.io   # URL pública para webhooks

# ════════════════════════════════════════════
# GOOGLE (Muninn — inalterado)
# ════════════════════════════════════════════
GOOGLE_PERSONAL_EMAIL=
GOOGLE_MUNINN_EMAIL=

# ════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════
LOG_DIR=./logs
LOG_TOKENS=true
VERBOSE=true

# ════════════════════════════════════════════
# MUNINN CLI (inalterado)
# ════════════════════════════════════════════
DEFAULT_MODEL=deepseek
```

---

## Referências

- [python-telegram-bot](https://python-telegram-bot.org/)
- [browser-use](https://github.com/browser-use/browser-use)
- [Playwright Python](https://playwright.dev/python/)
- [playwright-stealth](https://github.com/AtuboDad/playwright_stealth)
- [FastAPI](https://fastapi.tiangolo.com/)
- Muninn — `muninn.py`, `mcp_server.py`, `muninn_bridge.py`
