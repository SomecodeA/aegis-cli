# 🛡️ Aegis CLI — Bi-Directional AI Trading Loop

> **Kraken Agent Zero Contest Submission · 2026**

A standalone command-line tool that connects the [Kraken CLI binary](https://github.com/krakenfx/kraken-cli) to the Aegis trading bot's AI engine — forming a true bi-directional loop between live exchange data and multi-agent AI reasoning.

```
$ python3 aegis-cli.py --execute TAO --validate

  ✓ Live price: $283.94  (+7.15%)  H: $287.82  L: $252.89
  ✓ Using live Aegis Council API (real engine · journal intelligence)

  🐂 THE BULL  Strong V-recovery from $252 demand zone...
  🐻 THE BEAR  $287 rejection warrants caution...
  ⚖️ THE JUDGE  BUY 68% — TP $300 / SL $271

  ✓ Quality gate passed (68% ≥ 75% threshold)
  ✓ Balance: $413.98 available
  ✓ ORDER VALIDATED — 0.17619 TAO @ $283.94 = $50.00
```

---

## How it works

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  ┌──────────────────────┐        ┌──────────────────┐   │
│  │   Aegis Ecosystem    │        │     Kraken       │   │
│  │  ┌────────────────┐  │        │                  │   │
│  │  │   Aegis Bot    │  │        │  kraken ticker   │   │
│  │  │ (24/7 on VPS)  │  │        │  kraken balance  │   │
│  │  └───────┬────────┘  │        │  kraken order    │   │
│  │          │            │        │                  │   │
│  │  ┌───────▼────────┐  │        └────────┬─────────┘   │
│  │  │ Council of 3   │  │                 │             │
│  │  │ 🐂 🐻 ⚖️        │  │        ┌────────▼─────────┐   │
│  │  │ Claude AI      │  │        │                  │   │
│  │  └───────┬────────┘  │   ◄──► │   AEGIS CLI      │   │
│  └──────────┼───────────┘        │   (conductor)    │   │
│             │                    │                  │   │
│             └───────────────────►│                  │   │
│                                  └──────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**The CLI is the conductor.** It:
1. Fetches live price data from Kraken via the official CLI binary
2. Sends price data to the Aegis bot's Council of Three AI engine
3. Receives a multi-perspective verdict (Bull / Bear / Judge debate)
4. Checks your live balance via Kraken CLI
5. If the verdict clears the quality gate — places the order via Kraken CLI

---

## The Council of Three

The AI analysis is powered by **Aegis Bot's Council of Three** — a production multi-agent debate engine running 24/7 on a VPS. It is **not reimplemented in this CLI** — the CLI calls the bot's real engine via HTTP, ensuring verdicts are identical to those the bot generates.

Three AI personas powered by **Claude (Anthropic)** debate each asset:

| Persona | Role |
|---------|------|
| 🐂 **The Bull** | Argues momentum, demand zones, volume confirmation |
| 🐻 **The Bear** | Challenges exhaustion, resistance, downside risk |
| ⚖️ **The Judge** | Synthesises both views, issues final BUY / HOLD / SELL verdict |

The engine includes **2-day journal intelligence** — previous pulse verdicts and price history feed back into each new analysis, creating a continuously improving signal.

---

## Three workflows

### `--pulse <TICKER>` — AI analysis only

```bash
python3 aegis-cli.py --pulse TAO
python3 aegis-cli.py --pulse AAPLx    # xStocks supported
python3 aegis-cli.py --pulse ETH
```

Fetches live price from Kraken CLI → sends to Council of Three → renders Bull / Bear / Judge debate with verdict and confidence score.

### `--balance` — Live portfolio

```bash
python3 aegis-cli.py --balance
```

Calls `kraken balance -o json` to display your live Kraken portfolio. Demonstrates authenticated CLI access to private account data.

### `--execute <TICKER>` — Autonomous loop

```bash
# Validate without placing a real order (safe for testing)
python3 aegis-cli.py --execute TAO --validate

# Live execution — places a real order
python3 aegis-cli.py --execute TAO --amount 50

# Adjust quality gate threshold
python3 aegis-cli.py --execute TAO --gate 60
```

The full five-step autonomous loop:
1. **AI analysis** — Council of Three verdict via Aegis bot
2. **Quality gate** — blocks execution if not BUY or confidence below threshold
3. **Balance check** — verifies sufficient USD via `kraken balance`
4. **Price discovery** — fetches live price via `kraken ticker`
5. **Order execution** — places limit order via `kraken order buy`

---

## Installation

### Prerequisites

**1. Python 3.11+**
```bash
# macOS
brew install python@3.12

# Verify
python3 --version
```

**2. Kraken CLI binary**
```bash
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-installer.sh | sh

# Verify
kraken --version

# Authenticate with your Kraken API credentials
kraken auth set --api-key YOUR_KEY --api-secret YOUR_SECRET
```

**3. Python dependencies**
```bash
pip3 install anthropic rich aiohttp
```

### Setup

**Clone the repo:**
```bash
git clone https://github.com/YOUR_USERNAME/aegis-cli.git
cd aegis-cli
```

**Configure environment:**
```bash
cp .env.example .env
# Edit .env with your API keys and server details
```

**Run:**
```bash
python3 aegis-cli.py --balance
```

---

## Configuration

All configuration lives in `.env` — never hardcoded. Copy `.env.example` to `.env` and fill in your values.

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | Yes (fallback mode) |
| `SERPER_API_KEY` | Serper API for news context | Recommended |
| `AEGIS_COUNCIL_URL` | URL of your Aegis bot's Council API | Recommended |
| `COUNCIL_API_KEY` | Shared secret for Council API auth | If URL is set |
| `AEGIS_TRADE_AMOUNT` | Default USD trade size | No (default: $50) |
| `AEGIS_QUALITY_GATE` | Min confidence % to execute | No (default: 75%) |
| `AEGIS_DB_PATH` | Local path to Aegis bot's SQLite DB | Optional |

> **Never commit your `.env` file.** It is already in `.gitignore`.

---

## Connection to the Aegis bot

This CLI is a **standalone companion** to the [Aegis trading bot](https://github.com/YOUR_USERNAME/aegis-bot) — a 24/7 autonomous AI trading system running on a VPS.

The bot exposes a lightweight HTTP endpoint that the CLI calls for AI analysis:

```
POST /council
Content-Type: application/json
X-API-Key: <COUNCIL_API_KEY>

{
  "ticker": "TAO",
  "price": 283.94,
  "change_pct": 7.15,
  "high": 287.82,
  "low": 252.89
}
```

The bot runs the real `council_of_three_batch()` function — including journal intelligence, news context, and the full calibrated prompt system — and returns the verdict JSON.

**If the Council API is unreachable**, the CLI falls back to a standalone Anthropic API call using the same system prompt, ensuring it always produces a verdict.

To enable the Council API on your own Aegis bot instance, add to your bot's `.env`:
```
COUNCIL_API_KEY=your_shared_secret
COUNCIL_API_PORT=8765
```

And ensure port 8765 is mapped in your `docker-compose.yml`:
```yaml
ports:
  - "8765:8765"
```

---

## Project structure

```
aegis-cli/
├── aegis-cli.py       # Main CLI script (all logic in one file)
├── .env.example       # Configuration template — copy to .env
├── .gitignore         # Excludes .env, databases, and secrets
└── README.md          # This file
```

---

## Security notes

- **API keys** are loaded from `.env` at runtime — never hardcoded
- **Server IP and port** live in `.env` — never in source code
- The Council API requires a **shared secret** (`X-API-Key` header) to prevent public access
- **xStocks orders** include `asset_class=tokenized_asset` as required by Kraken
- All Kraken CLI calls use `-o json` for structured, parseable output
- The `--validate` flag is strongly recommended before any live execution

---

## Built with

- [Kraken CLI](https://github.com/krakenfx/kraken-cli) — official Kraken exchange CLI binary
- [Anthropic Claude](https://anthropic.com) — AI reasoning engine (Council of Three)
- [Rich](https://github.com/Textualize/rich) — beautiful terminal output
- [aiohttp](https://docs.aiohttp.org) — async HTTP for Council API calls

---

## License

MIT — free to use, modify, and build upon.

---

*Submitted to the [Kraken Agent Zero Contest](https://support.kraken.com/articles/agent-zero-promotion) · May 2026*
