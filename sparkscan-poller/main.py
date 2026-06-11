"""SparkScan → Centrifugo polling bridge.

Polls /v1/tokens/{token_id}/transactions every POLL_INTERVAL seconds and
publishes each new transaction to the Centrifugo channel named `Drq`.

Required env vars:
  SPARKSCAN_API_KEY      – SparkScan secret key
  CENTRIFUGO_API_URL     – e.g. http://centrifugo:8000/api/publish
  CENTRIFUGO_API_KEY     – Centrifugo API key

Optional env vars:
  QCHAINS_TOKEN          – token id (default: btkn1p3wa0svvmt7txqp92r9h930lxz3ldq3dhdvglf5prx4e67f6mywqtvsdaq)
  SPARKSCAN_BASE_URL     – default: https://api.sparkscan.io
  SPARKSCAN_NETWORK      – default: MAINNET
  CENTRIFUGO_CHANNEL     – default: Drq
  POLL_INTERVAL          – seconds between polls (default: 10)
  PAGE_SIZE              – transactions per poll request (default: 25)
"""

import logging
import os
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


SPARKSCAN_API_KEY = _require("SPARKSCAN_API_KEY")
CENTRIFUGO_API_URL = _require("CENTRIFUGO_API_URL")
CENTRIFUGO_API_KEY = _require("CENTRIFUGO_API_KEY")

QCHAINS_TOKEN = os.environ.get(
    "QCHAINS_TOKEN",
    "btkn1p3wa0svvmt7txqp92r9h930lxz3ldq3dhdvglf5prx4e67f6mywqtvsdaq",
)
SPARKSCAN_BASE_URL = os.environ.get("SPARKSCAN_BASE_URL", "https://api.sparkscan.io")
SPARKSCAN_NETWORK = os.environ.get("SPARKSCAN_NETWORK", "MAINNET")
CENTRIFUGO_CHANNEL = os.environ.get("CENTRIFUGO_CHANNEL", "Drq")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
PAGE_SIZE = int(os.environ.get("PAGE_SIZE", "25"))


def sparkscan_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"x-api-key": SPARKSCAN_API_KEY})
    return s


def centrifugo_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"apikey {CENTRIFUGO_API_KEY}",
            "Content-Type": "application/json",
        }
    )
    return s


def fetch_transactions(ss: requests.Session, offset: int = 0) -> list[dict]:
    url = f"{SPARKSCAN_BASE_URL}/v1/tokens/{QCHAINS_TOKEN}/transactions"
    resp = ss.get(
        url,
        params={"network": SPARKSCAN_NETWORK, "limit": PAGE_SIZE, "offset": offset},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # SparkScan wraps results in a list or under a key; handle both shapes.
    if isinstance(data, list):
        return data
    return data.get("transactions", data.get("items", data.get("data", [])))


def tx_id(tx: dict) -> str:
    """Return a stable unique identifier for a transaction."""
    return (
        tx.get("tx_hash")
        or tx.get("hash")
        or tx.get("txHash")
        or tx.get("id")
        or str(tx)
    )


def publish(cf: requests.Session, tx: dict) -> None:
    payload = {"channel": CENTRIFUGO_CHANNEL, "data": tx}
    resp = cf.post(CENTRIFUGO_API_URL, json=payload, timeout=10)
    if resp.status_code not in (200, 201):
        log.warning("Centrifugo publish failed: %s %s", resp.status_code, resp.text[:200])
    else:
        log.info("Published tx %s to channel %s", tx_id(tx), CENTRIFUGO_CHANNEL)


def seed_seen(ss: requests.Session) -> set[str]:
    """Fetch the current latest page and mark all as already seen so we don't
    replay historical transactions on first boot."""
    try:
        txs = fetch_transactions(ss)
        seen = {tx_id(t) for t in txs}
        log.info("Seeded %d known transactions (no replay on startup)", len(seen))
        return seen
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not seed seen set: %s — will start fresh", exc)
        return set()


def poll_loop() -> None:
    ss = sparkscan_session()
    cf = centrifugo_session()

    log.info(
        "SparkScan poller starting — token=%s network=%s channel=%s interval=%ds",
        QCHAINS_TOKEN,
        SPARKSCAN_NETWORK,
        CENTRIFUGO_CHANNEL,
        POLL_INTERVAL,
    )

    seen: set[str] = seed_seen(ss)

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            txs = fetch_transactions(ss)
        except Exception as exc:  # noqa: BLE001
            log.error("SparkScan fetch error: %s", exc)
            continue

        new_txs = [t for t in txs if tx_id(t) not in seen]
        if not new_txs:
            log.debug("No new transactions")
            continue

        # Publish oldest-first so subscribers see chronological order.
        for tx in reversed(new_txs):
            try:
                publish(cf, tx)
            except Exception as exc:  # noqa: BLE001
                log.error("Centrifugo publish error for tx %s: %s", tx_id(tx), exc)
            seen.add(tx_id(tx))

        # Bound the seen set to avoid unbounded memory growth.
        if len(seen) > 10_000:
            seen = set(list(seen)[-5_000:])


if __name__ == "__main__":
    poll_loop()
