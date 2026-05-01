# Production Checklist

Complete every item before switching from dry-run to live trading.

---

## Pre-live checklist

- [ ] **API keys present** — `HELIUS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` are set and validated by health check.
- [ ] **10–30 tracked wallets configured** — `data/wallets.json` contains wallet addresses you trust, with labels.
- [ ] **Telegram receives dry-run play alerts** — You have seen at least one `DRY RUN — PLAY DETECTED` message in your Telegram chat.
- [ ] **Paper trades recorded for at least 24 hours** — `python -m agent.cli paper-balance` shows buy/sell activity and a non-zero trade count.
- [ ] **Health checks green** — `python -m agent.cli health` shows `OK` for all required checks.
- [ ] **Max position cap reviewed** — `MAX_POSITION_SOL` is set to a conservative value (e.g., 2 SOL to start). Do not use the 10 SOL default on day one.
- [ ] **Wallet encrypted and funded with limited SOL** — Used `python -m agent.cli encrypt-wallet` to encrypt the private key. Hot wallet holds only what you can afford to lose (5–10 SOL recommended to start).
- [ ] **Rug DB seeded** — `data/rug_db.json` contains known rugger addresses. At minimum, verify the file exists and is valid JSON.
- [ ] **VPS backups configured** — You have a process to regularly back up `db/`, `logs/`, `data/`, and `.env`. See `docs/VPS_DEPLOY.md` for backup commands.
- [ ] **Alert fatigue check** — Telegram alerts fire only on plays, exits, and daily summaries. Not flooding with noise. Adjust `BUY_SCORE_THRESHOLD` and `MIN_APES` if too many alerts.
- [ ] **Emergency stop tested** — You have verified that `docker compose stop` halts all trading, and that `force-close --live` works on a test position.

---

## Post-live monitoring (first 48 hours)

- [ ] First live trade executed and Telegram alert received (no `DRY RUN` prefix).
- [ ] `python -m agent.cli positions` shows correct live position data.
- [ ] Stop-loss triggered correctly on at least one position (or verified logic in paper mode).
- [ ] No unexpected restarts — `docker compose logs` shows clean uptime.
- [ ] Memory and CPU within limits — `docker stats savage-agent` shows < 512 MB and < 100% CPU.
- [ ] Abort button on Telegram works — tapped Abort on a live alert and confirmed the position was not opened.
- [ ] Paper balance still being tracked for comparison if you kept `DRY_RUN_STARTING_SOL` in env.

---

## Periodic review (weekly)

- [ ] Review `python -m agent.cli trades --limit 50` for win rate and PnL trends.
- [ ] Check `python -m agent.cli tail-learning` for threshold adaptation activity.
- [ ] Verify wallet balance hasn't drifted unexpectedly — compare on-chain balance to expected.
- [ ] Update `data/rug_db.json` with any new known rugger addresses.
- [ ] Pull latest code and rebuild if updates are available.
- [ ] Verify backups are current.
