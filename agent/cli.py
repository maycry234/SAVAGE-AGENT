"""
SAVAGE AGENT — Operator CLI.

Usage:
    python -m agent.cli <command> [options]

Commands:
    generate-key       Generate a Fernet encryption key
    encrypt-wallet     Encrypt a wallet private key
    health             Run health checks
    positions          Show open positions
    trades             Show completed trades
    paper-balance      Show paper-trading balance
    reset-paper        Reset paper ledger
    force-close        Force-close a position
    tail-learning      Tail the learning log
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    try:
        return dict(row)
    except (TypeError, ValueError):
        if hasattr(row, "keys"):
            return {k: row[k] for k in row.keys()}
        return {}


def _json_serial(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def _print_table(headers: list[str], rows: list[list[str]]):
    if not rows:
        print("(no rows)")
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in col_widths]))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def _print_json(data):
    print(json.dumps(data, indent=2, default=_json_serial))


# ── Commands ────────────────────────────────────────────────────────────


def cmd_generate_key(_args):
    from agent.crypto_utils import generate_key

    key = generate_key()
    print(f"ENCRYPTION_KEY={key}")


def cmd_encrypt_wallet(args):
    from agent.crypto_utils import generate_key, encrypt_key
    from config import settings

    pk_input = args.private_key
    pk_path = Path(pk_input)
    if pk_path.is_file():
        raw = pk_path.read_text().strip()
    else:
        raw = pk_input

    if not raw:
        print("ERROR: private key is empty", file=sys.stderr)
        sys.exit(1)

    enc_key = args.key
    if not enc_key:
        enc_key = settings.ENCRYPTION_KEY
    generated = False
    if not enc_key:
        enc_key = generate_key()
        generated = True

    try:
        import base58
        key_bytes = base58.b58decode(raw)
    except Exception:
        key_bytes = raw.encode()

    encrypted = encrypt_key(key_bytes, enc_key)

    if generated:
        print(f"ENCRYPTION_KEY={enc_key}  # newly generated")
    else:
        print(f"ENCRYPTION_KEY={enc_key}")
    print(f"TRADER_WALLET_KEY={encrypted}")
    print("\nAdd both to your .env file. Never share the plaintext private key.", file=sys.stderr)


def cmd_health(_args):
    asyncio.run(_cmd_health_async())


async def _cmd_health_async():
    from agent.health import HealthChecker

    checker = HealthChecker()
    report = await checker.run_all()

    headers = ["CHECK", "REQUIRED", "OK", "LATENCY_MS", "DETAILS"]
    rows = []
    for r in report.results:
        rows.append([
            r.name,
            "yes" if r.required else "no",
            "OK" if r.ok else "FAIL",
            f"{r.latency_ms:.0f}",
            r.details,
        ])
    _print_table(headers, rows)

    if not report.ok:
        failed = [r.name for r in report.results if not r.ok and r.required]
        print(f"\nFailed required checks: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll required checks passed.")


def cmd_positions(args):
    asyncio.run(_cmd_positions_async(args))


async def _cmd_positions_async(args):
    from db import get_db

    db = await get_db("trades.db")
    try:
        cursor = await db.execute(
            "SELECT * FROM open_positions ORDER BY opened_at ASC"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    positions = [_row_to_dict(r) for r in rows]

    if args.json:
        _print_json(positions)
        return

    if not positions:
        print("No open positions.")
        return

    headers = [
        "SYMBOL", "TOKEN_ADDRESS", "SOL_IN", "TOKENS",
        "ENTRY", "CURRENT", "PEAK", "TP", "SL",
        "DRY", "REM%", "OPENED_AT",
    ]
    table_rows = []
    for p in positions:
        table_rows.append([
            p.get("token_symbol") or "?",
            p.get("token_address", "")[:12] + "...",
            f"{p.get('amount_sol', 0):.4f}",
            f"{p.get('amount_tokens', 0):.0f}",
            f"{p.get('entry_price', 0):.8f}",
            f"{p.get('current_price', 0):.8f}" if p.get("current_price") else "-",
            f"{p.get('peak_price', 0):.8f}" if p.get("peak_price") else "-",
            f"{p.get('tp_price', 0):.8f}" if p.get("tp_price") else "-",
            f"{p.get('sl_price', 0):.8f}" if p.get("sl_price") else "-",
            "yes" if p.get("dry_run") else "no",
            f"{(p.get('remaining_percent') or 1.0) * 100:.0f}",
            p.get("opened_at", ""),
        ])
    _print_table(headers, table_rows)
    print(f"\nTotal: {len(positions)} open position(s)")


def cmd_trades(args):
    asyncio.run(_cmd_trades_async(args))


async def _cmd_trades_async(args):
    from db import get_db

    limit = args.limit
    db = await get_db("trades.db")
    try:
        cursor = await db.execute(
            "SELECT * FROM completed_trades ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    trades = [_row_to_dict(r) for r in rows]

    if args.json:
        _print_json(trades)
        return

    if not trades:
        print("No completed trades.")
        return

    headers = [
        "SYMBOL", "TOKEN", "SOL_IN", "SOL_OUT",
        "PNL_SOL", "PNL%", "EXIT_REASON", "DRY", "CLOSED_AT",
    ]
    table_rows = []
    for t in trades:
        pnl_sol = t.get("pnl_sol", 0)
        pnl_pct = t.get("pnl_percent", 0)
        sign = "+" if pnl_sol >= 0 else ""
        table_rows.append([
            t.get("token_symbol") or "?",
            t.get("token_address", "")[:12] + "...",
            f"{t.get('amount_sol_in', 0):.4f}",
            f"{t.get('amount_sol_out', 0):.4f}",
            f"{sign}{pnl_sol:.4f}",
            f"{sign}{pnl_pct:.1f}%",
            t.get("exit_reason", ""),
            "yes" if t.get("dry_run") else "no",
            t.get("closed_at", ""),
        ])
    _print_table(headers, table_rows)
    print(f"\nShowing {len(trades)} trade(s) (limit {limit})")


def cmd_paper_balance(_args):
    asyncio.run(_cmd_paper_balance_async())


async def _cmd_paper_balance_async():
    from config import settings
    from agent.execution import ExecutionEngine
    from db import get_db

    engine = ExecutionEngine()
    balance = await engine.get_paper_balance()

    db = await get_db("trades.db")
    try:
        cursor = await db.execute(
            "SELECT "
            "  COALESCE(SUM(CASE WHEN event_type = 'BUY' THEN 1 ELSE 0 END), 0) as total_buys, "
            "  COALESCE(SUM(CASE WHEN event_type = 'SELL' THEN 1 ELSE 0 END), 0) as total_sells, "
            "  COALESCE(SUM(CASE WHEN event_type = 'BUY' THEN sol_delta ELSE 0 END), 0) as buy_sol, "
            "  COALESCE(SUM(CASE WHEN event_type = 'SELL' THEN sol_delta ELSE 0 END), 0) as sell_sol "
            "FROM paper_ledger WHERE event_type IN ('BUY', 'SELL')"
        )
        row = await cursor.fetchone()
        stats = _row_to_dict(row) if row else {}
    finally:
        await db.close()

    total_buys = stats.get("total_buys", 0)
    total_sells = stats.get("total_sells", 0)
    buy_sol = abs(stats.get("buy_sol", 0))
    sell_sol = stats.get("sell_sol", 0)
    realized_pnl = sell_sol - buy_sol

    print(f"Paper Balance:    {balance:.4f} SOL")
    print(f"Starting Balance: {settings.DRY_RUN_STARTING_SOL:.1f} SOL")
    print(f"Total Buys:       {total_buys}  ({buy_sol:.4f} SOL spent)")
    print(f"Total Sells:      {total_sells}  ({sell_sol:.4f} SOL received)")
    sign = "+" if realized_pnl >= 0 else ""
    print(f"Realized PnL:     {sign}{realized_pnl:.4f} SOL")


def cmd_reset_paper(args):
    if args.confirm != "RESET":
        print("ERROR: must pass --confirm RESET to confirm paper ledger reset", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_cmd_reset_paper_async())


async def _cmd_reset_paper_async():
    from agent.execution import ExecutionEngine

    engine = ExecutionEngine()
    balance_before = await engine.get_paper_balance()
    await engine.reset_paper_balance(reason="cli_manual_reset")
    balance_after = await engine.get_paper_balance()
    print(f"Paper ledger reset.")
    print(f"  Before: {balance_before:.4f} SOL")
    print(f"  After:  {balance_after:.4f} SOL")


def cmd_force_close(args):
    asyncio.run(_cmd_force_close_async(args))


async def _cmd_force_close_async(args):
    from config import settings
    from agent.execution import ExecutionEngine
    from db import get_db

    token = args.token
    percent = args.percent
    reason = args.reason
    is_live_flag = args.live

    if percent <= 0 or percent > 100:
        print("ERROR: --percent must be between 1 and 100", file=sys.stderr)
        sys.exit(1)

    db = await get_db("trades.db")
    try:
        cursor = await db.execute(
            "SELECT * FROM open_positions WHERE token_address = ?", (token,)
        )
        row = await cursor.fetchone()
    finally:
        await db.close()

    if not row:
        print(f"ERROR: no open position for token {token}", file=sys.stderr)
        sys.exit(1)

    pos = _row_to_dict(row)
    is_dry = bool(pos.get("dry_run"))
    remaining = pos.get("remaining_percent") or 1.0
    total_tokens = pos.get("amount_tokens", 0)

    if not is_dry:
        if settings.DRY_RUN:
            print("ERROR: position is live but agent is in DRY_RUN mode. Cannot sell live position in dry-run.", file=sys.stderr)
            sys.exit(1)
        if not is_live_flag:
            print("ERROR: this is a LIVE position. Pass --live to confirm live sell.", file=sys.stderr)
            sys.exit(1)

    sell_fraction = (percent / 100.0)
    if sell_fraction > remaining:
        sell_fraction = remaining
        print(f"WARNING: capped sell to remaining {remaining * 100:.0f}%", file=sys.stderr)

    sell_tokens = int(total_tokens * sell_fraction)
    if sell_tokens <= 0:
        print("ERROR: computed sell amount is 0 tokens", file=sys.stderr)
        sys.exit(1)

    engine = ExecutionEngine()
    await engine.initialize()

    result = await engine.sell_token(token, sell_tokens, reason)

    if not result.success:
        print(f"ERROR: sell failed: {result.error}", file=sys.stderr)
        sys.exit(1)

    sim_tag = " (simulated)" if getattr(result, "simulated", False) else ""
    print(f"Sell executed{sim_tag}:")
    print(f"  Token:     {token}")
    print(f"  Sold:      {percent:.0f}% ({sell_tokens} tokens)")
    print(f"  SOL out:   {result.sol_spent:.4f}")
    print(f"  TX sig:    {result.tx_signature}")

    new_remaining = remaining - sell_fraction
    if new_remaining <= 0.001:
        await _complete_position(pos, result, reason)
        print("  Position fully closed and moved to completed_trades.")
    else:
        db = await get_db("trades.db")
        try:
            await db.execute(
                "UPDATE open_positions SET remaining_percent = ?, last_updated = datetime('now') WHERE token_address = ?",
                (new_remaining, token),
            )
            await db.commit()
        finally:
            await db.close()
        print(f"  Remaining: {new_remaining * 100:.0f}%")

    await engine.close()


async def _complete_position(pos: dict, result, reason: str):
    from db import get_db

    entry_price = pos.get("entry_price", 0)
    amount_sol = pos.get("amount_sol", 0)
    sol_out = result.sol_spent
    pnl_sol = sol_out - amount_sol
    pnl_pct = (pnl_sol / amount_sol * 100) if amount_sol else 0

    opened_at = pos.get("opened_at", "")
    duration = 0
    if opened_at:
        try:
            opened_dt = datetime.fromisoformat(opened_at)
            from datetime import timezone as _tz
            opened_dt = opened_dt.replace(tzinfo=_tz.utc)
            duration = int((datetime.now(_tz.utc) - opened_dt).total_seconds())
        except (ValueError, TypeError):
            pass

    token = pos.get("token_address", "")
    dry_run = 1 if pos.get("dry_run") else 0

    db = await get_db("trades.db")
    try:
        await db.execute(
            "INSERT INTO completed_trades "
            "(token_address, token_symbol, entry_price, exit_price, "
            "amount_sol_in, amount_sol_out, pnl_sol, pnl_percent, "
            "exit_reason, duration_seconds, opened_at, dry_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                pos.get("token_symbol"),
                entry_price,
                result.sol_spent / max(pos.get("amount_tokens", 1), 1),
                amount_sol,
                sol_out,
                pnl_sol,
                pnl_pct,
                f"manual_close:{reason}",
                duration,
                opened_at,
                dry_run,
            ),
        )
        await db.execute(
            "DELETE FROM open_positions WHERE token_address = ?", (token,)
        )
        await db.commit()
    finally:
        await db.close()


def cmd_tail_learning(args):
    from config import settings

    log_path = settings.LOG_DIR / "learning.log"
    if not log_path.exists():
        print("No learning log yet.")
        sys.exit(0)

    lines = args.lines
    try:
        with open(log_path) as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        for line in tail:
            print(line, end="")
    except OSError as exc:
        print(f"ERROR: could not read learning log: {exc}", file=sys.stderr)
        sys.exit(1)


# ── Argparse setup ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent.cli",
        description="SAVAGE AGENT — Operator CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-key", help="Generate a Fernet encryption key")

    ew = sub.add_parser("encrypt-wallet", help="Encrypt a wallet private key")
    ew.add_argument("--private-key", required=True, help="Base58 private key or path to file containing it")
    ew.add_argument("--key", default="", help="Fernet encryption key (default: ENCRYPTION_KEY from env)")

    sub.add_parser("health", help="Run health checks")

    pos = sub.add_parser("positions", help="Show open positions")
    pos.add_argument("--json", action="store_true", help="Output as JSON")

    tr = sub.add_parser("trades", help="Show completed trades")
    tr.add_argument("--limit", type=int, default=20, help="Number of trades to show (default: 20)")
    tr.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("paper-balance", help="Show paper-trading balance")

    rp = sub.add_parser("reset-paper", help="Reset paper ledger")
    rp.add_argument("--confirm", required=True, help="Must be RESET to confirm")

    fc = sub.add_parser("force-close", help="Force-close a position")
    fc.add_argument("--token", required=True, help="Token mint address")
    fc.add_argument("--percent", type=float, required=True, help="Percent of position to close (1-100)")
    fc.add_argument("--reason", required=True, help="Exit reason string")
    fc.add_argument("--live", action="store_true", help="Required to sell live (non-dry-run) positions")

    tl = sub.add_parser("tail-learning", help="Tail the learning log")
    tl.add_argument("--lines", type=int, default=50, help="Number of lines (default: 50)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "generate-key": cmd_generate_key,
        "encrypt-wallet": cmd_encrypt_wallet,
        "health": cmd_health,
        "positions": cmd_positions,
        "trades": cmd_trades,
        "paper-balance": cmd_paper_balance,
        "reset-paper": cmd_reset_paper,
        "force-close": cmd_force_close,
        "tail-learning": cmd_tail_learning,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
