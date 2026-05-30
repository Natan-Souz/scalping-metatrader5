# Scalping MetaTrader5 — Triple Confirmation

Dois robôs de algotrading em Python para MetaTrader5 implementando a estratégia **Triple Confirmation** de scalping em pares forex.

> **Conta demo Pepperstone** — ordens reais enviadas via `mt5.order_send()`.

---

## Estratégia Triple Confirmation

Quatro critérios devem estar **todos alinhados** na mesma direção para abrir uma posição:

| # | Critério | BUY | SELL |
|---|---|---|---|
| C1 | EMA 9/21 M5 | Crossover para cima | Crossover para baixo |
| C2 | RSI(7) | Entre 50 e 70 | Entre 30 e 50 |
| C3 | MACD(12,26,9) | Linha > Signal | Linha < Signal |
| C4 | EMA 50 H1 | Preço acima | Preço abaixo |

**Candle analisado:** sempre o índice `-2` (último candle fechado — nunca o candle aberto).

**Gestão de risco:** `SL = 12 pips | TP = 24 pips (RR 1:2) | Risco = 1% do capital por trade`

---

## Bots

### `triple_confirmation.py` — Bot Single-Par
Opera exclusivamente **GBPUSD**. Máximo de 1 posição aberta por vez.

```powershell
python triple_confirmation.py
```

### `forex_scanner.py` — Scanner Multi-Par
Varre todos os pares forex disponíveis na corretora a cada 15 segundos.
Prioriza entradas pelo score (0–4), filtro de spread por categoria e controle de correlação.

```powershell
python forex_scanner.py
```

Ambos perguntam o capital em USD ao iniciar e calculam o lote automaticamente.

---

## Estrutura do Projeto

```
scalping-metatrader5/
│
├── core/                     ← código compartilhado pelos dois bots
│   ├── indicators.py         # calc_ema, calc_rsi, calc_macd (puro numpy)
│   ├── mt5_bridge.py         # connect, get_bars, get_pip_info, calc_lot, place_order
│   └── logging_setup.py      # setup_logging(log_file)
│
├── triple_bot/               ← lógica do bot single-par (GBPUSD)
│   ├── config.py             # constantes: SYMBOL, MAGIC=123456, SL_PIPS, etc.
│   ├── signal.py             # get_signal(), count_open_positions()
│   └── bot.py                # run(capital) + main()
│
├── scanner_bot/              ← lógica do scanner multi-par
│   ├── config.py             # constantes: SPREAD_MAX_*, SESSION_*, MAGIC=654321, etc.
│   ├── models.py             # CandidatoInfo (dataclass)
│   ├── filters.py            # pipeline Chain of Responsibility (8 filtros)
│   ├── symbols.py            # discover_forex_symbols, get_currencies
│   ├── states.py             # State Pattern (AguardandoSinal / GerenciandoPosicao)
│   └── robot.py              # ScannerRobot + main()
│
├── triple_confirmation.py    ← entry point (wrapper)
├── forex_scanner.py          ← entry point (wrapper)
└── .gitignore
```

---

## Pré-requisitos

- Python 3.10+
- MetaTrader5 aberto e logado na conta antes de iniciar qualquer bot

```powershell
pip install MetaTrader5 pandas numpy
```

---

## Configuração

Todas as constantes editáveis ficam nos arquivos `config.py` de cada pacote.
Alterar parâmetros de risco requer aprovação do fluxo **Tech Lead → Analista → Dev Senior**
conforme documentado em `.claude/CLAUDE.md`.

### Parâmetros principais

| Parâmetro | triple_bot | scanner_bot |
|---|---|---|
| `SYMBOL` | GBPUSD | todos os pares forex |
| `MAGIC` | 123456 | 654321 |
| `SL_PIPS` | 12 | 12 |
| `TP_RATIO` | 2.0 | 2.0 |
| `RISK_PCT` | 1% | 1% |
| `LOOP_SECONDS` | 15 | 15 |
| `MAX_POSITIONS` | 1 | 3 total / 1 por símbolo |

### Filtros exclusivos do scanner

| Parâmetro | Valor | Descrição |
|---|---|---|
| `SPREAD_MAX_MAJORS` | 2.5 pips | Limite de spread para pares Majors |
| `SPREAD_MAX_MINORS` | 4.0 pips | Limite de spread para pares Minors |
| `SPREAD_MAX_PCT_OF_SL` | 20% | Spread não pode exceder 20% do SL |
| `EMA_CROSSOVER_PIPS_THR` | 3.0 pips | Threshold de proximidade para pré-crossover |

---

## Como o Scanner Prioriza Entradas

1. **Descarta** Exotics, pares fora de sessão, spread alto
2. **Calcula** score 0–4 para cada par (1 ponto por critério alinhado)
3. **Ordena** por score desc → spread asc
4. **Score 4** → verifica correlação e abre posição
5. **Score 3** → log `[ALERTA]` no terminal, sem entrada
6. **Score ≤ 2** → log `DEBUG` apenas

**Correlação:** bloqueia qualquer par que compartilhe moeda base ou cotada com uma posição já aberta (ex: EUR/USD aberto → bloqueia EUR/JPY e GBP/USD).

---

## Logs

| Arquivo | Nível terminal | Nível arquivo |
|---|---|---|
| `triple_confirmation.log` | INFO | DEBUG |
| `forex_scanner.log` | INFO | DEBUG |

Os arquivos `.log` são gerados na raiz do projeto e ignorados pelo git.

---

## Aviso de Risco

Este software é fornecido para fins **educacionais e de pesquisa**.
Operar nos mercados financeiros envolve risco significativo de perda de capital.
Sempre teste em conta demo antes de qualquer uso em conta real.
