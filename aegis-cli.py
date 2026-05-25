#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           AEGIS CLI  ·  Bi-Directional AI Trading Loop                     ║
║           Kraken Agent Zero Contest Submission — 2026                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

A standalone CLI that fuses Aegis's "Council of Three" multi-agent AI debate
engine with the Kraken CLI binary to form a true bi-directional loop:

  AI LAYER  →  Bull / Bear / Judge debate → conviction verdict
  KRAKEN LAYER  →  live balance check → live price → order execution

Workflows:
  --pulse   <TICKER>   Full Council of Three AI analysis
  --balance            Live portfolio balance via Kraken CLI
  --execute <TICKER>   Autonomous bi-directional execution loop

Usage:
  python aegis-cli.py --pulse ETH
  python aegis-cli.py --balance
  python aegis-cli.py --execute TAO
  python aegis-cli.py --execute TAO --amount 100
  python aegis-cli.py --execute TAO --validate     (dry-run: no real order)

Requirements:
  - Kraken CLI binary installed and in PATH (kraken --version)
  - ANTHROPIC_API_KEY environment variable set
  - SERPER_API_KEY environment variable set (for news context)
  - Kraken CLI configured with API credentials
    (via ~/.config/kraken/config.toml or KRAKEN_API_KEY / KRAKEN_API_SECRET env vars)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ── Load .env file automatically ──────────────────────────────────────────────
# Looks for .env in the same directory as this script, then the current
# working directory. Does NOT require python-dotenv — pure stdlib.
def _load_dotenv() -> None:
    candidates = [
        Path(__file__).parent / ".env",   # same dir as aegis-cli.py
        Path.cwd() / ".env",              # wherever you run the script from
    ]
    for env_path in candidates:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:   # don't override shell exports
                        os.environ[key] = val
            break   # stop after first found

_load_dotenv()

# ── Rich terminal UI ───────────────────────────────────────────────────────────
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner
from rich.columns import Columns

console = Console()

# ── Config ─────────────────────────────────────────────────────────────────────
QUALITY_GATE_CONFIDENCE = int(os.getenv("AEGIS_QUALITY_GATE", "75"))
DEFAULT_TRADE_AMOUNT    = float(os.getenv("AEGIS_TRADE_AMOUNT", "50.0"))
COUNCIL_MODEL           = "claude-sonnet-4-6"
NEWS_MAX_CHARS          = 400     # max news context chars per ticker

# Path to the Aegis bot project — CLI imports the real Council engine from here.
# Set AEGIS_BOT_PATH in .env or it defaults to the sibling directory.
BOT_PATH = os.getenv("AEGIS_BOT_PATH", str(Path(__file__).parent.parent / "strategist"))

# Inject bot path so we can import aegis_execution, intelligence etc.
if os.path.isdir(BOT_PATH) and BOT_PATH not in sys.path:
    sys.path.insert(0, BOT_PATH)
    _USE_REAL_ENGINE = True
else:
    _USE_REAL_ENGINE = False   # fallback to standalone Council if bot not found

# ── Aegis branding ─────────────────────────────────────────────────────────────
AEGIS_BANNER = """
[bold cyan]    ╔═══════════════════════════════════════════╗[/]
[bold cyan]    ║  🛡️  AEGIS  ·  Council of Three  ·  CLI   ║[/]
[bold cyan]    ║     Bi-Directional AI Trading Loop        ║[/]
[bold cyan]    ╚═══════════════════════════════════════════╝[/]
"""


# =============================================================================
# Helpers
# =============================================================================

def _step(msg: str) -> None:
    """Print a formatted step message."""
    console.print(f"\n[bold white]❯[/] {msg}")


def _ok(msg: str) -> None:
    console.print(f"  [bold green]✓[/] {msg}")


def _warn(msg: str) -> None:
    console.print(f"  [bold yellow]⚠[/]  {msg}")


def _fail(msg: str) -> None:
    console.print(f"  [bold red]✗[/] {msg}")


def _check_env() -> bool:
    """Verify required environment variables and CLI binary are present."""
    ok = True
    if not os.getenv("ANTHROPIC_API_KEY"):
        _fail("ANTHROPIC_API_KEY not set — Council of Three requires this.")
        ok = False
    if not os.getenv("SERPER_API_KEY"):
        _warn("SERPER_API_KEY not set — news context will be skipped.")

    # DB intelligence context
    db_path = os.getenv("AEGIS_DB_PATH", "")
    if db_path and os.path.isfile(db_path):
        _ok("Journal DB found ✓ (intelligence context enabled)")
    elif db_path:
        _warn("AEGIS_DB_PATH set but file not found — check the path")
    else:
        _warn("AEGIS_DB_PATH not set — Council runs without journal context")
    try:
        result = subprocess.run(
            ["kraken", "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            ver = result.stdout.strip().split("\n")[0]
            _ok(f"Kraken CLI ready: {ver}")
        else:
            _fail("Kraken CLI found but returned an error.")
            ok = False
    except FileNotFoundError:
        _fail(
            "Kraken CLI binary not found in PATH.\n"
            "  Install via: curl --proto '=https' --tlsv1.2 -LsSf "
            "https://github.com/krakenfx/kraken-cli/releases/latest/"
            "download/kraken-installer.sh | sh"
        )
        ok = False
    except subprocess.TimeoutExpired:
        _fail("Kraken CLI timed out on --version check.")
        ok = False
    return ok


# =============================================================================
# Kraken CLI wrappers
# =============================================================================

def kraken_run(args: list[str], timeout: int = 15) -> dict:
    """
    Run a Kraken CLI command with -o json flag.
    Returns parsed JSON dict. Raises on non-zero exit or parse error.
    """
    cmd = ["kraken"] + args + ["-o", "json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=True
        )
        raw = result.stdout.strip()
        if not raw:
            return {}
        return json.loads(raw)
    except subprocess.CalledProcessError as e:
        # Kraken CLI returns structured JSON errors on stderr or stdout
        raw_err = e.stderr.strip() or e.stdout.strip()
        try:
            err_data = json.loads(raw_err)
            error_type = err_data.get("error", "unknown")
            error_msg  = err_data.get("message", raw_err)
            raise RuntimeError(
                f"Kraken CLI error [{error_type}]: {error_msg}"
            ) from e
        except (json.JSONDecodeError, KeyError):
            raise RuntimeError(
                f"Kraken CLI failed (exit {e.returncode}): {raw_err[:200]}"
            ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Kraken CLI timed out after {timeout}s") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Kraken CLI returned non-JSON output: {e}") from e


def get_live_price(ticker: str) -> tuple[float, float, float, float]:
    """
    Fetch live spot price AND 24H change % using: kraken ticker <PAIR> -o json
    Returns (price, change_pct, high_24h, low_24h) — full context for accurate Council analysis.
    Handles crypto (TAOUSD) and xStock (AAPLx/USD) formats.
    """
    is_xstock_ticker = ticker.upper().endswith("X") and len(ticker) > 2
    if is_xstock_ticker:
        pair       = f"{ticker}/USD"
        extra_args = ["--asset-class", "tokenized_asset"]
    else:
        pair       = f"{ticker.upper()}USD"
        extra_args = []

    try:
        data = kraken_run(["ticker", pair] + extra_args)

        def _extract(d: dict):
            # Extract last price
            price = None
            for key in ("last", "close", "c"):
                if key in d:
                    val = d[key]
                    if isinstance(val, list): val = val[0]
                    try: price = float(val); break
                    except (TypeError, ValueError): pass
            if not price:
                return None

            # Extract 24H high/low — Kraken "h"/"l" = [today, last_24h]
            high_24h = price
            low_24h  = price
            for hkey, lkey in [("h", "l"), ("high", "low"), ("high_24h", "low_24h")]:
                if hkey in d and lkey in d:
                    try:
                        hv = d[hkey]
                        lv = d[lkey]
                        if isinstance(hv, list): hv = hv[1]   # index 1 = rolling 24H
                        if isinstance(lv, list): lv = lv[1]
                        high_24h = float(hv)
                        low_24h  = float(lv)
                        break
                    except (TypeError, ValueError, IndexError):
                        pass

            # Extract 24H change via open price
            change_pct = 0.0
            for key in ("open", "o", "open_24h"):
                if key in d:
                    val = d[key]
                    if isinstance(val, list): val = val[0]
                    try:
                        op = float(val)
                        if op > 0:
                            change_pct = ((price - op) / op) * 100
                        break
                    except (TypeError, ValueError):
                        pass
            # Kraken "p" field = [today_avg, last_24h_avg]
            if change_pct == 0.0 and "p" in d:
                try:
                    pvals = d["p"]
                    if isinstance(pvals, list) and len(pvals) >= 2:
                        vwap_24h = float(pvals[1])
                        if vwap_24h > 0:
                            change_pct = ((price - vwap_24h) / vwap_24h) * 100
                except (TypeError, ValueError, IndexError):
                    pass

            return price, change_pct, high_24h, low_24h

        result = _extract(data)
        if result:
            return result

        for val in data.values():
            if isinstance(val, dict):
                result = _extract(val)
                if result:
                    return result

        raise RuntimeError(
            f"No price found in response: {list(data.keys())} — raw: {str(data)[:200]}"
        )

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Price fetch failed for {ticker}: {e}") from e


# =============================================================================
# News fetch (Serper — same as Aegis bot)
# =============================================================================

def get_news(ticker: str) -> str:
    """Fetch latest news context for ticker using Serper API."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return "No news context available (SERPER_API_KEY not set)."

    import urllib.request
    import urllib.error

    # xStocks: search for company name, not the tokenized ticker
    search_token = ticker.rstrip("xX") if ticker.upper().endswith("X") else ticker
    query = f"{search_token} stock price analysis" if ticker.upper().endswith("X") \
            else f"{ticker} crypto price news"

    payload = json.dumps({"q": query, "num": 5}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data     = json.loads(r.read())
            snippets = [
                item.get("snippet", "")
                for item in data.get("organic", [])[:4]
                if item.get("snippet")
            ]
            news = " | ".join(snippets)
            return news[:NEWS_MAX_CHARS] if news else "No recent news found."
    except Exception:
        return "News fetch failed."


# =============================================================================
# Council of Three — standalone (no Aegis DB dependency)
# =============================================================================

# Council system prompt is proprietary and lives in the Aegis bot.
# The CLI calls the bot's Council API endpoint directly (AEGIS_COUNCIL_URL).
# This fallback prompt is intentionally minimal — set AEGIS_COUNCIL_URL in .env
# to use the full calibrated Council of Three engine.
COUNCIL_SYSTEM = """You are a professional crypto trading analyst.
Analyse the provided market data and give a structured verdict.
Return ONLY a raw JSON array with exactly these keys:
ticker, bull, bear, verdict, confidence, summary, judge, hold_priority
- verdict: BUY, SELL, or HOLD
- confidence: integer 0-100
- bull, bear: max 40 words each
- judge: one sentence with verdict, confidence, TP/SL levels
- hold_priority: Low, Med, or High
- summary: single sentence, max 20 words"""


async def run_council(
    ticker:     str,
    price:      float,
    change_pct: float,
    news:       str,
    high_24h:   float = 0.0,
    low_24h:    float = 0.0,
) -> dict:
    """
    Calls the Aegis bot's Council API endpoint.
    The bot runs the real council_of_three_batch with full journal
    intelligence, news context, and calibrated system prompt.
    Falls back to standalone if the API is unreachable.
    """
    import aiohttp as _aiohttp

    api_url = os.getenv("AEGIS_COUNCIL_URL", "")
    api_key = os.getenv("COUNCIL_API_KEY", "")

    if api_url:
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-API-Key"] = api_key

            payload = {
                "ticker":     ticker.upper(),
                "price":      price,
                "change_pct": change_pct,
                "high":       high_24h,
                "low":        low_24h,
            }
            async with _aiohttp.ClientSession() as session:
                async with session.post(
                    api_url, json=payload, headers=headers,
                    timeout=_aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        _ok("Using [bold cyan]live Aegis Council API[/] "
                            f"(real engine · journal intelligence included)")
                        return result
                    else:
                        _warn(f"Council API returned HTTP {resp.status} — using standalone")
        except Exception as e:
            _warn(f"Council API unreachable ({e}) — using standalone")

    # ── Standalone fallback ───────────────────────────────────────────────────
    import anthropic

    # Inject journal intelligence from local DB copy if available
    intel_context = ""
    db_path = os.getenv("AEGIS_DB_PATH", "")
    if db_path and os.path.isfile(db_path):
        try:
            import sqlite3, json as _json
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(db_path) as _conn:
                _conn.row_factory = sqlite3.Row
                rows = _conn.execute(
                    "SELECT entry_text, created_at FROM journal "
                    "WHERE ticker=? AND created_at>=? ORDER BY created_at DESC LIMIT 5",
                    (ticker.upper(), cutoff)
                ).fetchall()
            if rows:
                lines = [f"=== INTEL: {ticker.upper()} (last 2d, {len(rows)} entries) ==="]
                for i, row in enumerate(reversed(rows), 1):
                    ts = str(row["created_at"])[:16]
                    try:
                        d = _json.loads(row["entry_text"])
                        lines.append(
                            f"[{i}] {ts}  {d.get('verdict','')} "
                            f"{d.get('confidence','')}%  {str(d.get('summary',''))[:120]}"
                        )
                    except Exception:
                        lines.append(f"[{i}] {ts}  {str(row['entry_text'])[:100]}")
                lines.append("=== END INTEL ===")
                intel_context = "\n".join(lines)
                _ok(f"Journal intelligence loaded: [bold cyan]{len(rows)} entries[/]")
        except Exception as e:
            _warn(f"Journal context unavailable: {e}")

    full_news = f"{intel_context}\n\nLATEST NEWS:\n{news}" if intel_context else news

    client    = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    chg_str   = ("+{:.2f}".format(change_pct) if change_pct >= 0 else "{:.2f}".format(change_pct))
    market_row = (
        f"{ticker} | ${price:.4f} | {chg_str}%"
        f" | H:{high_24h:.4f} L:{low_24h:.4f} | 4H | {full_news[:600]}"
    )
    prompt = (
        f"{market_row}\n\n"
        f"Run the Council of Three 4H debate for: {ticker}\n"
        f"Return ONLY the JSON array."
    )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model=COUNCIL_MODEL,
            max_tokens=600,
            system=COUNCIL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    raw    = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)
    return parsed[0] if isinstance(parsed, list) else parsed


# =============================================================================
# Workflow A: --pulse
# =============================================================================

async def workflow_pulse(ticker: str) -> Optional[dict]:
    """Full Council of Three analysis with beautiful terminal output."""
    console.print(AEGIS_BANNER)
    console.print(Rule(f"[bold cyan]COUNCIL OF THREE · {ticker.upper()}[/]"))

    # Step 1: Live price from Kraken CLI
    _step(f"[cyan]Querying Kraken CLI for live {ticker} price...[/]")
    try:
        price, change_pct, high_24h, low_24h = get_live_price(ticker)
        _ok(f"Live price: [bold green]${price:,.4f}[/]  "
            f"([{'bold green' if change_pct >= 0 else 'bold red'}]{change_pct:+.2f}%[/])  "
            f"H: [white]${high_24h:,.4f}[/]  L: [white]${low_24h:,.4f}[/]")
    except RuntimeError as e:
        _fail(str(e))
        return None

    # Step 2: News context
    _step("[cyan]Fetching market intelligence & news context...[/]")
    news = get_news(ticker)
    _ok("News context loaded")

    # Step 3: Council debate
    _step("[cyan]Convening the Council of Three...[/]")
    console.print()

    analysis = None
    with console.status(
        "[bold cyan]🛡️  Bull · Bear · Judge debating...[/]",
        spinner="dots"
    ):
        try:
            analysis = await run_council(
                ticker=ticker.upper(),
                price=price,
                change_pct=change_pct,
                news=news,
                high_24h=high_24h,
                low_24h=low_24h,
            )
        except Exception as e:
            _fail(f"Council failed: {e}")
            return None

    # ── Render the Council report ─────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold white]COUNCIL DELIBERATION[/]"))

    # Bull panel
    console.print(Panel(
        f"[bold white]{analysis['bull']}[/]",
        title="[bold green]🐂 THE BULL[/]",
        border_style="green",
        padding=(1, 2),
    ))

    # Bear panel
    console.print(Panel(
        f"[bold white]{analysis['bear']}[/]",
        title="[bold red]🐻 THE BEAR[/]",
        border_style="red",
        padding=(1, 2),
    ))

    # Judge panel
    console.print(Panel(
        f"[bold white]{analysis['judge']}[/]",
        title="[bold yellow]⚖️  THE JUDGE[/]",
        border_style="yellow",
        padding=(1, 2),
    ))

    # Verdict box
    verdict    = analysis.get("verdict", "HOLD").upper()
    confidence = analysis.get("confidence", 0)
    summary    = analysis.get("summary", "")

    verdict_colour = {
        "BUY":  "bold green",
        "SELL": "bold red",
        "HOLD": "bold yellow",
    }.get(verdict, "bold white")

    console.print()
    console.print(Panel(
        f"[{verdict_colour}]{verdict}[/]  ·  "
        f"[bold white]{confidence}% confidence[/]\n\n"
        f"[italic white]{summary}[/]",
        title=f"[bold white]🛡️  AEGIS VERDICT · {ticker.upper()}[/]",
        border_style="cyan",
        padding=(1, 2),
    ))

    console.print()
    return analysis


# =============================================================================
# Workflow B: --balance
# =============================================================================

def workflow_balance() -> Optional[dict]:
    """Fetch and display live portfolio balance via Kraken CLI."""
    console.print(AEGIS_BANNER)
    console.print(Rule("[bold cyan]LIVE PORTFOLIO · Kraken CLI[/]"))

    _step("[cyan]Authenticating with Kraken CLI...[/]")
    try:
        data = kraken_run(["balance"])   # kraken balance -o json
        _ok("Credentials verified — portfolio loaded")
    except RuntimeError as e:
        _fail(str(e))
        return None

    # Parse balances — CLI returns {asset: amount_string}
    balances = {}
    if isinstance(data, dict):
        # Strip Kraken's Z prefix from fiat (ZUSD → USD)
        for asset, amount in data.items():
            clean_name = asset.lstrip("Z") if len(asset) > 1 else asset
            amt = float(amount) if amount else 0.0
            if amt > 0:
                balances[clean_name] = amt

    if not balances:
        _warn("No non-zero balances found.")
        return {}

    console.print()
    table = Table(
        title="[bold cyan]💼 LIVE PORTFOLIO BALANCE[/]",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold white",
        show_lines=True,
    )
    table.add_column("Asset",   style="bold cyan",  min_width=8)
    table.add_column("Balance", style="bold white",  min_width=14, justify="right")
    table.add_column("Est. USD", style="bold green", min_width=14, justify="right")

    usd_balance = balances.get("USD", 0.0)
    total_usd   = usd_balance

    for asset, amount in sorted(balances.items(), key=lambda x: -x[1]):
        if asset == "USD":
            table.add_row("USD  💵", f"{amount:,.2f}", f"${amount:,.2f}")
        else:
            table.add_row(asset, f"{amount:.8f}", "—")

    console.print(table)
    console.print()
    console.print(Panel(
        f"[bold green]Available USD: ${usd_balance:,.2f}[/]\n"
        f"[white]Powered by Kraken CLI authenticated REST[/]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()
    return balances


# =============================================================================
# Workflow C: --execute (The Bi-Directional Loop)
# =============================================================================

async def workflow_execute(
    ticker:   str,
    amount:   float = DEFAULT_TRADE_AMOUNT,
    validate: bool  = False,
    demo:     bool  = False,
) -> None:
    """
    The full autonomous bi-directional loop:
      AI analysis → quality gate → balance check → price check →
      quantity calculation → Kraken CLI order → confirmation
    """
    console.print(AEGIS_BANNER)
    console.print(Rule("[bold cyan]AUTONOMOUS EXECUTION LOOP[/]"))

    mode_str = "[bold yellow]VALIDATE MODE (no real order)[/]" if validate \
               else "[bold red]LIVE EXECUTION MODE[/]"
    console.print(f"\n  Mode: {mode_str}")
    console.print(f"  Target: [bold cyan]{ticker.upper()}[/]  ·  "
                  f"Amount: [bold white]${amount:.2f}[/]\n")

    # ── Step 1: Council Analysis ──────────────────────────────────────────────
    console.print(Rule("[dim]Step 1 of 5 · AI Analysis[/]"))
    console.print(
        f"\n[bold white]❯[/] [cyan]Evaluating market context for "
        f"[bold]{ticker.upper()}[/]...[/]\n"
    )

    if demo:
        # Demo mode: inject a high-conviction BUY for video recording
        console.print(Panel(
            "[dim italic]⚡ DEMO MODE — injecting high-conviction BUY signal "
            "to demonstrate execution path[/]",
            border_style="dim", padding=(0, 2)
        ))
        # Still fetch live price for authenticity
        try:
            _demo_price, _demo_chg, _demo_h, _demo_l = get_live_price(ticker)
            _ok(f"Live price: [bold green]${_demo_price:,.4f}[/]  "
                f"([{'bold green' if _demo_chg >= 0 else 'bold red'}]{_demo_chg:+.2f}%[/])")
        except RuntimeError as e:
            _fail(str(e)); return
        analysis = {
            "bull":       f"{ticker} breaking above key resistance with expanding volume. "
                          f"AI narrative momentum and on-chain accumulation confirm bullish thesis.",
            "bear":       "Resistance at current level has rejected price twice. "
                          "Macro headwinds and funding rates elevated.",
            "judge":      f"Volume confirmation + AI sector momentum gives {ticker} the edge. "
                          f"BUY on breakout with tight stop below support.",
            "verdict":    "BUY",
            "confidence": 82,
            "summary":    f"{ticker} exhibits high-conviction breakout setup with volume confirmation "
                          f"and sector momentum. Entry justified with defined risk.",
        }
        # Render Council panels
        console.print()
        console.print(Rule("[bold white]COUNCIL DELIBERATION[/]"))
        console.print(Panel(f"[bold white]{analysis['bull']}[/]",
                            title="[bold green]🐂 THE BULL[/]", border_style="green", padding=(1,2)))
        console.print(Panel(f"[bold white]{analysis['bear']}[/]",
                            title="[bold red]🐻 THE BEAR[/]", border_style="red", padding=(1,2)))
        console.print(Panel(f"[bold white]{analysis['judge']}[/]",
                            title="[bold yellow]⚖️  THE JUDGE[/]", border_style="yellow", padding=(1,2)))
        console.print(Panel(
            f"[bold green]BUY[/]  ·  [bold white]82% confidence[/]\n\n"
            f"[italic white]{analysis['summary']}[/]",
            title=f"[bold white]🛡️  AEGIS VERDICT · {ticker.upper()}[/]",
            border_style="cyan", padding=(1,2)
        ))
        console.print()
    else:
        analysis = await workflow_pulse(ticker)
        if not analysis:
            _fail("Council analysis failed. Execution aborted.")
            return

    verdict    = analysis.get("verdict", "HOLD").upper()
    confidence = int(analysis.get("confidence", 0))

    # ── Step 2: Quality Gate ──────────────────────────────────────────────────
    console.print(Rule("[dim]Step 2 of 5 · Quality Gate[/]"))
    console.print(
        f"\n[bold white]❯[/] Evaluating against quality gate "
        f"(threshold: [bold]{QUALITY_GATE_CONFIDENCE}%[/])...\n"
    )

    time.sleep(0.5)   # dramatic pause for the video

    if verdict != "BUY":
        console.print(Panel(
            f"[bold red]🛑 ENTRY BLOCKED — Signal Mismatch[/]\n\n"
            f"Verdict: [bold yellow]{verdict}[/] · Confidence: {confidence}%\n\n"
            f"[white]Aegis only executes on BUY signals.\n"
            f"Capital preserved.[/]",
            border_style="red",
            padding=(1, 2),
        ))
        return

    if confidence < QUALITY_GATE_CONFIDENCE:
        console.print(Panel(
            f"[bold red]🛑 ENTRY BLOCKED — Quality Gate[/]\n\n"
            f"Confidence: [bold yellow]{confidence}%[/]  "
            f"< Required: [bold white]{QUALITY_GATE_CONFIDENCE}%[/]\n\n"
            f"[white]Conviction too low. Execution aborted to preserve capital.[/]",
            border_style="red",
            padding=(1, 2),
        ))
        return

    console.print(Panel(
        f"[bold green]🛡️  QUALITY GATE PASSED — High Conviction Detected[/]\n\n"
        f"Verdict: [bold green]{verdict}[/] · "
        f"Confidence: [bold green]{confidence}%[/]\n\n"
        f"[white]Transitioning to autonomous execution...[/]",
        border_style="green",
        padding=(1, 2),
    ))

    # ── Step 3: Balance Check ─────────────────────────────────────────────────
    console.print()
    console.print(Rule("[dim]Step 3 of 5 · Balance Verification[/]"))
    _step("[cyan]Querying live portfolio balance via Kraken CLI...[/]")

    try:
        balance_data = kraken_run(["balance"])   # kraken balance -o json
        usd_balance  = float(balance_data.get("ZUSD", balance_data.get("USD", 0)))
        _ok(f"Available USD: [bold green]${usd_balance:,.2f}[/]")
    except RuntimeError as e:
        _fail(f"Balance check failed: {e}")
        return

    if usd_balance < amount:
        console.print(Panel(
            f"[bold red]🛑 INSUFFICIENT FUNDS[/]\n\n"
            f"Required: [bold white]${amount:.2f}[/]  "
            f"Available: [bold red]${usd_balance:.2f}[/]\n\n"
            f"[white]Reduce --amount or deposit funds.[/]",
            border_style="red",
            padding=(1, 2),
        ))
        return

    # ── Step 4: Live Price & Quantity Calculation ─────────────────────────────
    console.print()
    console.print(Rule("[dim]Step 4 of 5 · Price Discovery & Quantity[/]"))
    _step(f"[cyan]Fetching live {ticker.upper()} price from Kraken CLI...[/]")

    try:
        live_price, live_chg, live_h, live_l = get_live_price(ticker)
        _ok(f"Live price: [bold green]${live_price:,.4f}[/]  "
            f"([{'bold green' if live_chg >= 0 else 'bold red'}]{live_chg:+.2f}%[/])  "
            f"H: [white]${live_h:,.4f}[/]  L: [white]${live_l:,.4f}[/]")
    except RuntimeError as e:
        _fail(f"Price fetch failed: {e}")
        return

    quantity = round(amount / live_price, 8)
    _ok(
        f"Order: [bold white]BUY {quantity:.8f} {ticker.upper()}[/]  "
        f"@ [bold white]${live_price:,.4f}[/]  "
        f"= [bold green]${amount:.2f}[/]"
    )

    # ── Step 5: Order Execution ───────────────────────────────────────────────
    console.print()
    console.print(Rule("[dim]Step 5 of 5 · Order Execution[/]"))

    if validate:
        _step("[yellow]VALIDATE mode — building order (no real execution)...[/]")
    else:
        _step("[bold red]Dispatching LIVE order to Kraken CLI...[/]")

    time.sleep(0.8)   # dramatic pause

    # Build CLI command
    is_xstock   = ticker.upper().endswith("X") and len(ticker) > 2
    pair        = f"{ticker}/USD" if is_xstock else f"{ticker.upper()}USD"
    order_args  = [
        "order", "buy", pair, str(quantity),
        "--type", "market",
    ]
    if is_xstock:
        order_args += ["--asset-class", "tokenized_asset"]
    if validate:
        order_args += ["--validate"]

    cli_str = "kraken " + " ".join(order_args) + " -o json"
    console.print(f"\n  [dim]Command:[/] [bold white]{cli_str}[/]\n")

    try:
        order_result = kraken_run(order_args, timeout=20)

        # Parse txid from result
        txids = order_result.get("result", {}).get("txid", [])
        descr = order_result.get("result", {}).get("descr", {})
        order_descr = descr.get("order", f"buy {quantity} {ticker.upper()}")

        if validate:
            console.print(Panel(
                f"[bold yellow]✅ ORDER VALIDATED (not submitted)[/]\n\n"
                f"[white]Description:[/] [bold white]{order_descr}[/]\n"
                f"[white]Quantity:[/] [bold white]{quantity:.8f} {ticker.upper()}[/]\n"
                f"[white]Est. Cost:[/] [bold green]${amount:.2f}[/]\n\n"
                f"[dim]Remove --validate to place the real order.[/]",
                border_style="yellow",
                padding=(1, 2),
            ))
        else:
            txid_str = txids[0] if txids else "confirmed"
            console.print(Panel(
                f"[bold green]✅ ORDER PLACED SUCCESSFULLY[/]\n\n"
                f"[white]Transaction ID:[/] [bold cyan]{txid_str}[/]\n"
                f"[white]Description:[/]   [bold white]{order_descr}[/]\n"
                f"[white]Quantity:[/]      [bold white]{quantity:.8f} {ticker.upper()}[/]\n"
                f"[white]Price:[/]         [bold green]${live_price:,.4f}[/]\n"
                f"[white]Total Cost:[/]    [bold green]${amount:.2f}[/]\n\n"
                f"[dim]Powered by Kraken CLI · Decided by Aegis Council of Three[/]",
                border_style="green",
                padding=(1, 2),
            ))

    except RuntimeError as e:
        console.print(Panel(
            f"[bold red]✗ ORDER FAILED[/]\n\n"
            f"[white]{e}[/]\n\n"
            f"[dim]Check API permissions and account balance.[/]",
            border_style="red",
            padding=(1, 2),
        ))
        return

    # ── Final Summary ─────────────────────────────────────────────────────────
    console.print()
    console.print(Rule("[bold cyan]EXECUTION COMPLETE[/]"))
    console.print(Panel(
        "[bold cyan]🛡️  AEGIS · Bi-Directional AI Loop Complete[/]\n\n"
        f"[white]AI Layer:[/]     Council of Three ({COUNCIL_MODEL})\n"
        f"[white]Exchange Layer:[/] Kraken CLI (native binary)\n"
        f"[white]Result:[/]       [bold green]{verdict} {ticker.upper()} @ ${live_price:,.4f}[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()


# =============================================================================
# Entry Point
# =============================================================================

def main():
    global QUALITY_GATE_CONFIDENCE   # declared first — used later in argparse default + override
    parser = argparse.ArgumentParser(
        prog="aegis-cli",
        description=(
            "🛡️  AEGIS CLI — Bi-Directional AI Trading Loop\n"
            "Kraken Agent Zero Contest Submission\n\n"
            "Fuses the Aegis Council of Three AI debate engine with\n"
            "the Kraken CLI binary for autonomous market analysis and execution."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python aegis-cli.py --pulse ETH\n"
            "  python aegis-cli.py --balance\n"
            "  python aegis-cli.py --execute TAO\n"
            "  python aegis-cli.py --execute TAO --amount 100\n"
            "  python aegis-cli.py --execute TAO --validate\n"
        )
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--pulse", metavar="TICKER",
        help="Run Council of Three AI analysis for TICKER (e.g. ETH, TAO, AAPLx)"
    )
    group.add_argument(
        "--balance",
        action="store_true",
        help="Show live portfolio balance via Kraken CLI"
    )
    group.add_argument(
        "--execute", metavar="TICKER",
        help="Run full autonomous loop: AI analysis → quality gate → live order"
    )
    parser.add_argument(
        "--amount", type=float, default=DEFAULT_TRADE_AMOUNT, metavar="USD",
        help=f"USD amount to trade (default: ${DEFAULT_TRADE_AMOUNT:.0f})"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Dry-run: validate order without real execution"
    )
    parser.add_argument(
        "--gate", type=int, default=QUALITY_GATE_CONFIDENCE, metavar="PCT",
        help=f"Quality gate confidence threshold %% (default: {QUALITY_GATE_CONFIDENCE})"
    )

    parser.add_argument(
        "--demo", action="store_true",
        help="Demo mode: inject high-conviction BUY to show full execution path"
    )

    args = parser.parse_args()

    # Apply CLI override
    QUALITY_GATE_CONFIDENCE = args.gate

    # Pre-flight check
    console.print()
    _step("[dim]Running pre-flight checks...[/]")
    if not _check_env():
        console.print()
        _fail("Pre-flight failed. Fix the above issues and retry.")
        sys.exit(1)

    # Dispatch
    if args.pulse:
        asyncio.run(workflow_pulse(args.pulse))

    elif args.balance:
        workflow_balance()

    elif args.execute:
        asyncio.run(workflow_execute(
            ticker=args.execute,
            amount=args.amount,
            validate=args.validate,
            demo=args.demo,
        ))


if __name__ == "__main__":
    main()
