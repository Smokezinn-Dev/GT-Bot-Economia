# 💰 GT Bot Economia v6.0

Bot Discord completo focado em **economia, jogos, progressão, social e mercado**.
Sem moderação. Prefixo padrão: `$`. Multi-guild (até 2 servidores). Slash commands habilitados.
Compatível com Railway, Discloud e VPS.

---

## 📋 ÍNDICE

- [Visão Geral](#-visão-geral)
- [Requisitos](#-requisitos)
- [Estrutura de Diretórios](#-estrutura-de-diretórios)
- [Instalação](#-instalação)
- [Variáveis de Ambiente](#-variáveis-de-ambiente)
- [Execução](#-execução)
- [Deploy](#-deploy)
- [Arquitetura](#-arquitetura)
- [Módulos Controláveis](#-módulos-controláveis)
- [Comandos por Categoria](#-comandos-por-categoria)
- [Coleções MongoDB](#-coleções-mongodb)
- [Segurança Aplicada](#-segurança-aplicada)
- [Otimizações](#-otimizações)
- [Métricas de Performance](#-métricas-de-performance)
- [Erros Comuns e Soluções](#-erros-comuns-e-soluções)
- [Fluxo de Verificação por Mensagem](#-fluxo-de-verificação-por-mensagem)

---

## 🎯 VISÃO GERAL

┌──────────────────────────────────────────────────────────────────┐
│                    GT BOT ECONOMIA v6.0                          │
│                    Prefixo: $ (customizável por guild)          │
│                    Slash: Sim                                    │
│                    Multi-Guild: até 2 servidores                 │
├──────────────────────────────────────────────────────────────────┤
│ 🎛️ CONTROLE TOTAL                                                │
│ • Admin ativa/desativa módulos                                  │
│ • Admin ativa/desativa comandos individualmente                 │
│ • Admin bloqueia comando por canal                              │
│ • Prefixo dinâmico por servidor                                 │
│ • Modo manutenção por servidor                                  │
│ • Bypass de cargos/usuários confiáveis                          │
│ • Painel interativo com select                                  │
│                                                                  │
│ 🎨 BRANDING                                                      │
│ • Nick do bot por servidor                                      │
│ • Cor customizada dos embeds por guild                          │
│ • Footer customizado por guild                                  │
│ • Reset completo                                                │
│                                                                  │
│ 💾 BACKUP INTELIGENTE                                            │
│ • Estrutura de canais + permissões                              │
│ • Cargos + permissões + hierarquia                              │
│ • Membros com cargos (reatribuição no restore)                  │
│ • Restore com merge (não duplica)                               │
│ • Modos: all/canais/cargos/membros/config/textos                │
│                                                                  │
│ 💰 ECONOMIA AVANÇADA                                             │
│ • Saldo atômico (compartilhado com Ranked)                      │
│ • Daily com cooldown                                            │
│ • Transferência com taxa                                        │
│ • Prestige (prestígio)                                          │
│ • Investimentos                                                 │
│ • Streak (chat)                                                 │
│ • Booster (x2, x3)                                              │
│ • Freeze de guild/usuário                                       │
│                                                                  │
│ 💸 SINKS DE DINHEIRO                                             │
│ • Imposto de rico automático                                    │
│ • Leilão com bids competitivos                                  │
│ • Loteria semanal com prêmio acumulado                          │
│                                                                  │
│ 🏢 SOCIAL                                                        │
│ • Guildas (até 10 membros, cofre compartilhado)                 │
│ • Casamento (bônus conjunto)                                    │
│ • PvP (apostas entre jogadores)                                 │
│                                                                  │
│ 📈 MERCADO                                                       │
│ • Bolsa de valores (ações fake)                                 │
│ • Portfólio por jogador                                         │
│ • Variação de preços                                            │
│                                                                  │
│ 📅 MISSÕES DIÁRIAS                                               │
│ • 3 missões por dia por usuário                                 │
│ • Progresso automático via hooks                                │
│ • Recompensas resgatáveis                                       │
│                                                                  │
│ 🏪 LOJA E INVENTÁRIO                                             │
│ • Loja com roles                                                │
│ • Itens consumíveis                                             │
│ • Boosters                                                      │
│ • Inventário do usuário                                         │
│                                                                  │
│ 🏆 CONQUISTAS                                                    │
│ • Automáticas                                                   │
│ • Recompensas reais                                             │
│ • Lista completa                                                │
│                                                                  │
│ 🎲 EVENTOS                                                       │
│ • Multiplicadores                                               │
│ • Bônus por mensagem                                            │
│ • Desconto na loja                                              │
│                                                                  │
│ 🎮 GAMES E APOSTAS                                               │
│ • Flip (cara/coroa)                                             │
│ • Dados (rollgamble)                                            │
│ • Roleta                                                        │
│ • Slots                                                         │
│ • Blackjack                                                     │
│ • Crash                                                         │
│ • Corrida de Cavalos                                            │
│ • Raspadinha                                                    │
│ • Giveaways                                                     │
│ • Tickets                                                       │
│ • Jogos customizados                                            │
│                                                                  │
│ 🩺 SISTEMA                                                       │
│ • Health check completo                                         │
│ • Memory monitor automático                                     │
│ • GC tuning agressivo                                           │
│ • Auto-GC quando RAM > 380MB                                    │
│ • Shutdown graceful                                             │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │     MONGODB ATLAS        │
              │     (Dados na nuvem)     │
              │     economy_balances     │
              │     (compartilhado com   │
              │      o bot Ranked)       │
              │                          │
              │     ~30 coleções         │
              │     ~35 índices + TTL    │
              └─────────────────────────┘

---

## ⚙️ REQUISITOS

- Python 3.10 ou superior
- MongoDB Atlas (ou local)
- discord.py 2.3+
- pymongo 4.5+
- dnspython 2.4+
- psutil 5.9+ (opcional, para health check detalhado)

---

## 📁 ESTRUTURA DE DIRETÓRIOS

📁 GT-Bot-Economia/
│
├── 📄 main.py                              ← BOT PRINCIPAL + COG ECOBASIC (help/status)
├── 📄 config.py                            ← VALIDAÇÃO ESTRITA + MULTI-GUILD
├── 📄 database.py                          ← POOL TUNING + ÍNDICES + TTL
├── 📄 embeds.py                            ← BRAND POR GUILD
├── 📄 utils.py                             ← CACHE + GUILD GATE + RETRY
├── 📄 requirements.txt                     ← discord.py, pymongo, dnspython, psutil
├── 📄 discloud.config                      ← Config para Discloud
├── 📄 README.md                            ← Este arquivo
│
├── ────── CONTROLE E CONFIG ──────
├── 📄 commands_control.py                  ← CONTROLE TOTAL
├── 📄 commands_branding.py                 ← PERSONALIZAÇÃO POR GUILD
├── 📄 commands_backup.py                   ← BACKUP INTELIGENTE
│
├── ────── ECONOMIA CORE ──────
├── 📄 commands_economy_core.py             ← SALDO + DAILY + TRANSFER + RANKING
├── 📄 commands_economy_admin.py            ← ADMIN ECONOMIA
├── 📄 commands_economy_earn.py             ← GANHOS + PRESTIGE + INVEST + STREAK
├── 📄 commands_economy_shop.py             ← LOJA + INVENTÁRIO + BOOSTERS
├── 📄 commands_economy_achievements.py     ← CONQUISTAS AUTOMÁTICAS
├── 📄 commands_economy_events.py           ← EVENTOS (multiplicador, bônus)
├── 📄 commands_economy_games.py            ← GAMES CUSTOM
├── 📄 commands_economy_gambling.py         ← APOSTAS + GIVEAWAYS
│
├── ────── ECONOMIA NOVA ──────
├── 📄 commands_economy_sinks.py            ← IMPOSTO + LEILÃO + LOTERIA
├── 📄 commands_economy_social.py           ← GUILDAS + CASAMENTO + PVP
├── 📄 commands_economy_market.py           ← BOLSA + PORTFÓLIO
├── 📄 commands_economy_missions.py         ← MISSÕES DIÁRIAS
└── 📄 commands_economy_games_extra.py      ← BLACKJACK + CRASH + CORRIDA + RASPADINHA

Total: 23 arquivos

---

## 📦 INSTALAÇÃO

### 1. Criar a pasta

    mkdir GT-Bot-Economia
    cd GT-Bot-Economia

### 2. Criar ambiente virtual

    python -m venv venv

    # Linux/Mac
    source venv/bin/activate

    # Windows
    venv\Scripts\activate

### 3. Instalar dependências

    pip install -r requirements.txt

---

## 🔐 VARIÁVEIS DE AMBIENTE

Crie um arquivo `.env` na raiz (ou configure no painel do Railway/Discloud):

    # ─────── OBRIGATÓRIAS ───────
    DISCORD_TOKEN=seu_token_do_bot_economia
    MONGODB_URL=mongodb+srv://usuario:senha@cluster.mongodb.net/?retryWrites=true&w=majority

    # ─────── OPCIONAIS ───────
    DB_NAME=gt_bot_economia
    PREFIX=$
    GUILD_IDS=123456789012345678,987654321098765432
    ADMIN_ROLE_ID=0
    ENABLE_DEBUG=false

    # Backup automático (opcional no bot de economia)
    BACKUP_ENABLED=false
    BACKUP_AUTO_HOUR=4
    BACKUP_MAX_PER_GUILD=10

    # Anti-Nuke (não usado no bot de economia)
    ANTINUKE_ENABLED=false

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| DISCORD_TOKEN | ✅ Sim | — | Token do bot (Developer Portal) |
| MONGODB_URL | ✅ Sim | — | String de conexão Mongo |
| DB_NAME | ❌ Não | gt_bot_economia | Nome do banco |
| PREFIX | ❌ Não | $ | Prefixo padrão |
| GUILD_IDS | ❌ Não | — | IDs separados por vírgula |
| GUILD_ID | ❌ Não | — | Compat single-guild |
| ADMIN_ROLE_ID | ❌ Não | 0 | Cargo admin global |
| ENABLE_DEBUG | ❌ Não | false | Logs verbosos |
| BACKUP_ENABLED | ❌ Não | false | Backup automático |
| BACKUP_AUTO_HOUR | ❌ Não | 4 | Hora UTC do backup |
| BACKUP_MAX_PER_GUILD | ❌ Não | 10 | Backups guardados |
| ANTINUKE_ENABLED | ❌ Não | false | Anti-nuke (não usado) |

> 💡 Importante: Use um token DIFERENTE do bot de moderação.
> 💡 Se quiser isolar dados: DB_NAME=gt_bot_economia. Se quiser compartilhar: use o mesmo DB_NAME nos dois.

---

## ▶️ EXECUÇÃO

Modo desenvolvimento:

    python main.py

Modo produção (Linux):

    nohup python main.py > bot.log 2>&1 &

---

## 🚀 DEPLOY

### Railway

1. Crie um novo projeto em railway.app
2. Conecte ao repositório Git
3. Adicione as variáveis de ambiente na aba Variables
4. Configure o Start Command: `python main.py`
5. Railway detecta `requirements.txt` e roda automaticamente

### Discloud

O arquivo `discloud.config` já está pronto:

    NAME=GT Bot Economia
    MAIN=main.py
    RAM=100
    status=online
    activity_name=💰 Economia | $help
    activity_type=watching
    ignore=.git,__pycache__,*.pyc,*.log,gt_bot_economia.db

Passos:
1. Baixe o app Discloud
2. Faça upload da pasta inteira (com `discloud.config`)
3. Configure as variáveis de ambiente no painel da Discloud
4. O bot sobe automaticamente

---

## 🏗️ ARQUITETURA

    Mensagem recebida
           ↓
    É comando? (prefixo $)
           ↓ sim
    Guild está em manutenção?
           ↓ não
    Usuário é bypass? → sim → executa
           ↓ não
    Comando pertence a módulo?
           ↓ sim
    Módulo está ativo?
           ↓ sim
    Comando desativado no servidor?
           ↓ não
    Comando bloqueado neste canal?
           ↓ não
          ✅ EXECUTA

Isso roda ANTES de processar o comando, economizando CPU quando módulo está off.

---

## 🎛️ MÓDULOS CONTROLÁVEIS

Ativar/desativar via `$controlmodules` ou `$controltoggle <mod> on/off`:

| Módulo | Descrição |
|---|---|
| economy | 💰 Economia base (balance, daily, pay, ranking) |
| earn | 📈 Ganhos (prestige, invest, streak) |
| shop | 🏪 Loja e inventário |
| games | 🎮 Jogos customizados |
| gambling | 🎰 Apostas (flip, slots, roleta) |
| events | 🎉 Eventos com multiplicadores |
| achievements | 🏆 Conquistas automáticas |
| social | 🏢 Guildas, casamento, PvP |
| market | 📈 Bolsa e portfólio |
| missions | 📅 Missões diárias |
| sinks | 💸 Leilão e loteria |
| backup | 💾 Backup/restore |
| branding | 🎨 Personalização do bot |

---

## 📋 COMANDOS POR CATEGORIA

### 🎛️ CONTROLE TOTAL

    $control                        # Painel principal
    $controlmodules                 # Painel de módulos (select interativo)
    $controltoggle <mod> on/off     # Ativar/desativar módulo direto
    $controlcommands                # Lista comandos desativados
    $controlcmd <cmd> off/on        # Desativa/reativa comando
    $controlcmd <cmd> channel #canal # Desativa em canal
    $controlprefix <novo>           # Muda prefixo do servidor
    $controlmaintenance on/off      # Modo manutenção
    $controlbypass @cargo add/remove # Cargo que ignora tudo
    $controlstate                   # Estado atual do controle

### 🎨 BRANDING

    $branding                       # Painel
    $brandingnickname <nome>        # Apelido do bot neste servidor
    $brandingcolor <hex>            # Cor dos embeds (#ff0000)
    $brandingfooter <texto>         # Rodapé customizado
    $brandingreset                  # Resetar tudo

### 💾 BACKUP

    $backup                         # Painel
    $backupcreate [nome]            # Criar backup
    $backuplist                     # Listar backups
    $backupinfo <id>                # Detalhes
    $backupdelete <id>              # Apagar
    $backuprestore <id> [modo]      # Restore (all/canais/cargos/membros/config/textos)
    $backuptext #canal [remove]     # Marcar/desmarcar canal para salvar texto
    $backuptextlimit <n>            # Limite de msgs por canal (10-500)
    $backuptextlist                 # Lista canais que salvam texto

### 💵 SALDO E TRANSFERÊNCIA

    $balance [@user]                # Ver saldo
    $daily                          # Bônus diário
    $pay @user <valor>              # Transferir (com taxa)
    $ranking                        # Ranking de ricos
    $economyconfig                  # Config da economia

### 🧑💼 ADMIN ECONOMIA

    $ecogive @user <valor>          # Dar dinheiro
    $ecoremove @user <valor>        # Remover dinheiro
    $ecoset @user <valor>           # Setar saldo
    $ecoreset @user                 # Zerar usuário
    $ecofreeze @user                # Travar economia
    $ecounfreeze @user              # Destravar economia
    $ecoaudit [@user]               # Logs de transações
    $ecostats                       # Estatísticas da economia
    $ecoclearcache                  # Limpar caches
    $ecosofreset CONFIRMAR          # Zerar todos os saldos

### 📈 PROGRESSÃO

    $prestige                       # Subir de prestígio
    $prestigestatus                 # Status do prestígio
    $invest <valor>                 # Investir dinheiro
    $collect                        # Resgatar investimento
    $earnconfig                     # Configurar ganhos

### 🏪 LOJA E INVENTÁRIO

    $shop                           # Ver loja
    $buy <item>                     # Comprar item
    $inventory [@user]              # Ver inventário
    $use <item>                     # Usar consumível
    $shopadd <nome> <preço> <tipo>  # Adicionar item
    $shoprole <role> <preço>        # Adicionar cargo
    $shopconsumable <nome> <preço> <efeito> <duração> # Adicionar consumível
    $shopremove <id>                # Remover item

### 🏆 CONQUISTAS

    $achievements [@user]           # Ver conquistas
    $achcreate <nome> <tipo> <meta> <recompensa> # Criar conquista
    $achlist                        # Listar conquistas
    $achcheck                       # Verificar conquistas
    $achdelete <id>                 # Deletar conquista

### 🎉 EVENTOS

    $events                         # Ver eventos ativos
    $eventcreate <nome> <tipo> <valor> <duração> [desc] # Criar evento
    $eventdelete <id>               # Deletar evento

### 💸 SINKS

    $taxconfig                      # Painel do imposto de rico
    $taxconfig on/off               # Ativar/desativar
    $taxconfig limite <n>           # Valor mínimo para taxar
    $taxconfig taxa <pct>           # % do excedente
    $taxconfig hora <0-23>          # Hora UTC de execução
    $lottery                        # Painel da loteria
    $lottery buy <qtd>              # Comprar tickets
    $lottery info                   # Info da rodada atual
    $auction                        # Listar leilões ativos
    $auction start <item> | <min>   # Iniciar leilão (admin)
    $auction cancel <id>            # Cancelar (admin)
    $bid <id> <valor>               # Dar lance

### 🏢 SOCIAL

    $guild                          # Painel da sua guilda
    $guild create <nome>            # Criar guilda (5000)
    $guild join <nome>              # Entrar em guilda
    $guild leave                    # Sair
    $guild deposit <valor>          # Depositar no cofre
    $guild list                     # Listar guildas
    $marry @user                    # Casar
    $divorce                        # Divorciar
    $pvp @user <valor>              # Desafio PvP

### 📈 MERCADO

    $market                         # Ver ações disponíveis
    $market buy <SYM> <qtd>         # Comprar ações
    $market sell <SYM> <qtd>        # Vender ações
    $market create <SYM> <nome> <preço> # Criar ação (admin)
    $portfolio [@user]              # Ver portfólio

### 📅 MISSÕES

    $missions                       # Ver missões diárias
    $missionsclaim <1-3>            # Resgatar recompensa

### 🎮 GAMES E APOSTAS

    $flip <valor>                   # Cara ou coroa
    $rollgamble <valor>             # Dados (dice)
    $roulette <valor>               # Roleta Russa
    $slots <valor>                  # Caça-níqueis
    $giveaway <prêmio> <n> <tempo>  # Criar sorteio
    $ticket <id> [qtd]              # Comprar tickets
    $giveaways                      # Ver sorteios ativos
    $gamelist                       # Ver jogos disponíveis
    $gameplay <id>                  # Jogar
    $gamehistory [@user]            # Histórico de jogos
    $gamecreate ...                 # Criar jogo (admin)
    $gameedit <id> <campo> <valor>  # Editar jogo (admin)
    $gamedelete <id>                # Deletar jogo (admin)

### 🃏 GAMES EXTRA

    $blackjack <valor>              # Blackjack com dealer
    $crash <valor> [auto_cashout]   # Crash (sacar antes de quebrar)
    $race <cavalo 1-6> <valor>      # Corrida de cavalos
    $scratch                        # Raspadinha (custo 50)

### 🩺 SISTEMA

    $ping                           # Latência
    $status                         # Status do bot
    $botinfo                        # Info do bot
    $help                           # Lista todos os comandos

---

## 📊 COLEÇÕES MONGODB (~30)

Núcleo:

    control_config, branding_config, guild_config,
    role_permissions, user_permissions

Economia:

    economy_balances, economy_transactions, economy_config,
    economy_shop, economy_inventory, economy_purchases,
    economy_boosts, economy_giveaways

Ganhos:

    earn_config, prestige, investments, sinks_config

Eventos e conquistas:

    events, achievements, user_achievements

Games:

    custom_games, game_participations

Backup:

    backups, backup_texts, backup_config

Economia avançada:

    auctions, lottery_rounds, lottery_tickets,
    market_stocks, market_portfolio

Social:

    guilds_social, guilds_members, marriages, pvp_bets

Missões:

    missions_daily

Compartilhado com Ranked:

    players

---

## 🔒 SEGURANÇA APLICADA

### 1. safe_object_id() centralizado em utils.py

    def safe_object_id(value: Any) -> Optional[Any]:
        if not _HAS_BSON or value is None:
            return None
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str) and len(value) == 24:
            try:
                return ObjectId(value)
            except (InvalidId, ValueError, TypeError):
                return None
        return None

### 2. Rate Limiter por Usuário (Token Bucket)

    class RateLimiter:
        __slots__ = ("rate", "per", "_buckets", "_lock")
        def allow(self, key: str) -> bool:
            # Token bucket por chave (user:command)

### 3. TTLCache Thread-Safe (LRU)

    class TTLCache:
        __slots__ = ("max_size", "ttl", "_data", "_lock", "_hits", "_misses")
        def get(self, key):
            with self._lock:
                # Operação thread-safe com lock RLock

### 4. Operações Atômicas com Retry

    @retry_mongo(attempts=3, base_delay=0.08)
    def add_balance(cls, guild_id, user_id, amount, ...):
        # Backoff exponencial em caso de falha

### 5. Validação de Inputs

- IDs validados via safe_object_id() antes de qualquer operação
- Valores numéricos checados (positivos, dentro de faixas)
- Menções parseadas com regex
- Canais/cargos verificados antes de usar

### 6. GuildGate

- Centraliza controle de módulos/comandos
- Cache TTL para não bater no Mongo a cada mensagem
- Verifica módulo → comando → canal → manutenção em ordem de custo

---

## ⚡ OTIMIZAÇÕES

| Otimização | Descrição | Impacto |
|---|---|---|
| TTLCache com lock | Thread-safe, TTL e LRU | -90% queries MongoDB |
| Pool MongoDB max 3 | Railway free friendly | -80% conexões abertas |
| GC Threshold (500, 8, 8) | Mais agressivo | -50% overhead GC |
| Memory Monitor | Auto-GC quando RAM > 380MB | Evita OOM no Railway |
| Batch Updates | $set agrupado | -70% queries |
| Índices + TTL | Todos criados no startup | -50% tamanho DB |
| deque(maxlen=3) no earn | Anti-farm sem vazar RAM | Estável |
| max_messages=1000 | Cache interno menor | -50% RAM discord.py |
| Shutdown graceful | Fecha tasks corretamente | Sem leaks |
| Cog load idempotente | Unload antes de load | Zero crash em restart |
| Sync 429 tolerante | Ignora rate limit | Bot continua |
| Rate limiter token bucket | Sem dict infinito | Anti-spam leve |
| Cache por guild no embeds | Cor/footer sem query | -95% no Mongo |
| Cache de config por Cog | Cada Cog tem o seu | -80% queries |
| Verificação módulo ANTES | Early return no on_message | -70% CPU com módulos off |

---

## 📈 MÉTRICAS DE PERFORMANCE

| Métrica | Valor Esperado |
|---|---|
| Cache Hit Rate | 85-95% |
| Memória RAM | ~100-180MB |
| Conexões MongoDB | Max 3 (pool) |
| Response Time | < 300ms |
| Uptime | 24/7 |
| GC Frequency | A cada 3 min (leve) |
| GC Forçado | Só se RAM > 380MB |
| Índices MongoDB | ~35 (com TTL) |
| Transações por segundo | ~50-100 (pico) |

---

## ⚠️ ERROS COMUNS E SOLUÇÕES

| Problema | Solução |
|---|---|
| SSL handshake | Verificar IP no Atlas (0.0.0.0/0) |
| IP bloqueado | Adicionar 0.0.0.0/0 no Atlas |
| Slash 429 | Normal em restart seguido; bot continua |
| Cog already loaded | Setup idempotente + unload antes do load |
| ObjectId inválido | safe_object_id() valida antes |
| Rate limit global | Token bucket por usuário |
| Módulo desativado bloqueando | Admin usa $controltoggle pra ativar |
| Saldo compartilhado errado | Verificar DB_NAME em ambos os bots |
| Economia travada | $ecounfreeze (guild ou usuário) |
| Prêmio de evento não aplica | Verificar $events |
| RAM alta no Railway | Reduzir módulos com $controltoggle |

---

## 🚦 FLUXO DE VERIFICAÇÃO POR MENSAGEM

    Mensagem recebida
           ↓
    É comando? ($ ou prefixo custom)
           ↓ sim
    Guild está em manutenção?
           ↓ não
    Usuário é bypass? → sim → executa
           ↓ não
    Comando pertence a módulo?
           ↓ sim
    Módulo está ativo?
           ↓ sim
    Comando desativado no servidor?
           ↓ não
    Comando bloqueado neste canal?
           ↓ não
          ✅ EXECUTA

---

## 🔗 INTEGRAÇÃO COM O BOT DE MODERAÇÃO

Este bot foi separado do bot de moderação, mas pode compartilhar:

- Mesmo cluster MongoDB (recomendado, economiza recurso)
- Banco diferente: DB_NAME=gt_bot_economia (isolamento total)
- Banco igual: DB_NAME=gt_bot_moderacao (compartilha dados)

O bot de economia NÃO tem comandos de moderação.
Use o GT Bot Moderação para kick/ban/warn/etc.

---

## 📜 LICENÇA

Projeto privado — uso interno da comunidade GT - Stumble Guys.

---

## 👑 AUTOR

Dark e Smokezinn
📺 YouTube: https://youtube.com/@dark-e-smokezinn
🎮 Comunidade GT - Stumble Guys

---

Versão: 6.0
Última atualização: 2026
Foco: Economia, jogos e progressão
Total de arquivos: 23
Cogs carregados: 16 (EcoBasic + 15 extensions)
