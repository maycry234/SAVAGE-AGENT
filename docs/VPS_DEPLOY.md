# VPS Deployment Runbook

Step-by-step guide for deploying SAVAGE AGENT on a VPS with Docker Compose.

---

## Server Requirements

- **OS:** Ubuntu 22.04 or 24.04 LTS
- **Hardware:** 1 vCPU, 1 GB RAM minimum (2 GB recommended)
- **Disk:** 10 GB free (SQLite DBs + logs)
- **Docker:** Docker Engine 24+ with Docker Compose v2
- **Network:** Outbound HTTPS (443) to Helius, Jupiter, DexScreener, Telegram, xAI

### Firewall basics

```bash
# Allow SSH only, deny everything inbound
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable
```

No inbound ports are required — the agent only makes outbound connections.

---

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
docker --version
docker compose version
```

---

## 2. Clone and configure

```bash
git clone https://github.com/maycry234/SAVAGE-AGENT.git
cd SAVAGE-AGENT
git checkout main

cp .env.example .env
```

Edit `.env` with your keys:

```bash
nano .env
```

Required variables:

| Variable | Where to get it |
|---|---|
| `HELIUS_API_KEY` | [helius.dev](https://helius.dev) — free tier works |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Send `/start` to your bot, then call `https://api.telegram.org/bot<token>/getUpdates` |

Leave `DRY_RUN=true` (the default) for initial deployment.

---

## 3. Add tracked wallets

Edit `data/wallets.json` with 10–30 wallet addresses you want to monitor for convergent ape activity.

---

## 4. Run health check

```bash
docker compose run --rm savage-agent python -m agent.cli health
```

All required checks (helius_rpc, helius_rest, dexscreener, jupiter, telegram) must show `OK`. Fix any `FAIL` entries before proceeding.

---

## 5. Start in dry-run mode

```bash
docker compose up -d --build
```

Verify the container is running:

```bash
docker compose ps
```

---

## 6. Tail logs

```bash
docker compose logs -f savage-agent
```

Look for:
- `DRY RUN enabled` on startup
- `loaded N tracked wallets`
- Health check results
- Signal and scoring activity

---

## 7. Inspect paper trading state

```bash
# Paper balance
docker compose run --rm savage-agent python -m agent.cli paper-balance

# Open positions (paper)
docker compose run --rm savage-agent python -m agent.cli positions

# Completed trades
docker compose run --rm savage-agent python -m agent.cli trades --limit 20

# Learning log
docker compose run --rm savage-agent python -m agent.cli tail-learning
```

---

## 8. Burn-in checklist (24–72 hours)

Run the agent in dry-run for at least 24 hours. During this period, verify:

- [ ] Telegram receives play alerts with `DRY RUN` prefix
- [ ] Paper trades are being recorded (`paper-balance` shows activity)
- [ ] No crash loops (check `docker compose logs` for repeated restarts)
- [ ] Health check passes consistently (`docker compose run --rm savage-agent python -m agent.cli health`)
- [ ] Memory usage stays within limits (`docker stats savage-agent`)
- [ ] Token scoring produces reasonable scores (check trade history)
- [ ] Alert fatigue is acceptable (not too many / too few alerts)
- [ ] WebSocket reconnects cleanly after network blips

---

## 9. Live mode switch

After a successful burn-in, follow this checklist **in order**:

### Pre-flight

1. **Fund hot wallet** with limited SOL only (start with 5–10 SOL). Never store more than you're willing to lose.

2. **Generate encryption key and encrypt wallet:**
   ```bash
   docker compose run --rm savage-agent python -m agent.cli generate-key
   docker compose run --rm savage-agent python -m agent.cli encrypt-wallet \
     --private-key <your_base58_key> --key <your_encryption_key>
   ```

3. **Update `.env`:**
   ```bash
   DRY_RUN=false
   ENCRYPTION_KEY=<from step 2>
   TRADER_WALLET_KEY=<from step 2>
   MAX_POSITION_SOL=2.0   # start conservative
   ```

4. **Restart:**
   ```bash
   docker compose down
   docker compose up -d --build
   ```

5. **Verify live mode:**
   ```bash
   docker compose logs savage-agent | head -50
   # Should show: "execution engine initialized, wallet=<pubkey>"
   # Should NOT show: "DRY RUN enabled"
   ```

6. **Confirm Telegram abort flow** — wait for a live play alert and tap the Abort button to verify it works.

7. **Test manual force-close** on a small position:
   ```bash
   docker compose run --rm savage-agent python -m agent.cli force-close \
     --token <mint> --percent 100 --reason test_close --live
   ```

---

## 10. Backup and restore

### Backup

The agent stores all state in three mounted volumes:

```bash
# Stop to ensure clean backup
docker compose stop

# Archive
tar czf savage-backup-$(date +%Y%m%d).tar.gz db/ logs/ data/ .env

# Restart
docker compose start
```

### Restore

```bash
docker compose stop
tar xzf savage-backup-YYYYMMDD.tar.gz
docker compose up -d
```

---

## 11. Updating the bot

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose down
docker compose up -d --build

# Verify health
docker compose run --rm savage-agent python -m agent.cli health
docker compose logs savage-agent | head -30
```

If an update changes the DB schema, the agent handles migrations automatically on startup via `_add_column_if_missing`.

---

## 12. Emergency procedures

### Stop immediately

```bash
docker compose stop
```

This halts all trading. Open positions remain in the DB. No new buys or sells will execute.

### Force-close a live position

```bash
docker compose run --rm savage-agent python -m agent.cli force-close \
  --token <mint_address> --percent 100 --reason emergency --live
```

The `--live` flag is required for real (non-dry-run) positions.

### Force-close all positions

```bash
docker compose run --rm savage-agent python -m agent.cli positions --json \
  | python3 -c "
import json, sys, subprocess
positions = json.load(sys.stdin)
for p in positions:
    addr = p['token_address']
    dry = p.get('dry_run', 0)
    cmd = ['docker', 'compose', 'run', '--rm', 'savage-agent',
           'python', '-m', 'agent.cli', 'force-close',
           '--token', addr, '--percent', '100', '--reason', 'emergency_all']
    if not dry:
        cmd.append('--live')
    subprocess.run(cmd)
"
```

### Rotate wallet keys

1. Generate a new Solana keypair externally.
2. Transfer remaining SOL from old wallet to new wallet.
3. Re-encrypt with the CLI:
   ```bash
   docker compose run --rm savage-agent python -m agent.cli encrypt-wallet \
     --private-key <new_base58_key>
   ```
4. Update `ENCRYPTION_KEY` and `TRADER_WALLET_KEY` in `.env`.
5. Restart: `docker compose down && docker compose up -d --build`

### Switch back to dry-run

```bash
# In .env
DRY_RUN=true

docker compose down
docker compose up -d
```

All existing live positions remain in the DB but no new live trades will execute. You can still force-close live positions with `--live`.
