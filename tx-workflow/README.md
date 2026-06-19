# tx-workflow

SparkScan route planner + Flashnet swap executor.
Converts QCHAINS / DRQ → BTC → USDB via live Flashnet bonding pools.

## Setup

```bash
npm install
# For live execution, also install the signer (on your local machine only):
npm install @buildonspark/spark-sdk
```

## Step 1 — Plan (read-only, no keys needed)

```bash
export SPARKSCAN_API_KEY="ss_sk_live_..."
node plan.mjs
```

Prints live balances, pool reserves, and the exact USDB amount deliverable.

## Step 2 — Wet run (SDK initialises + reads live balance, does NOT broadcast)

```bash
export SPARKSCAN_API_KEY="ss_sk_live_..."
export SPARK_MNEMONIC="word1 word2 ... word12"   # your NEW wallet's seed
export DEST_SPARK_ADDRESS="spark1..."             # new wallet to sweep into
node execute.mjs
```

Stops before signing because `CONFIRM=YES` is absent. Safe to run.

## Step 3 — Live execution

Add `CONFIRM=YES` once you've reviewed the wet-run output:

```bash
CONFIRM=YES node execute.mjs
```

## Key constants (never hardcode secrets)

| Env var | Description |
|---|---|
| `SPARKSCAN_API_KEY` | SparkScan read key |
| `SPARK_MNEMONIC` | 12-word seed for your **new** wallet |
| `DEST_SPARK_ADDRESS` | Destination spark address for sweep |
| `CONFIRM` | Set to `YES` to arm live broadcast |

## ⚠️ Security notes

- Never screenshot or paste your seed phrase into chat or any web UI
- Rotate `SPARKSCAN_API_KEY` if it has been shared in a chat session
- The executor will refuse to run without both `SPARK_MNEMONIC` and `CONFIRM=YES`
