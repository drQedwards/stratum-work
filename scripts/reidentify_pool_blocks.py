#!/usr/bin/env python3
"""
Iterate the MongoDB 'blocks' collection in height-ordered chunks and re-run
the pool identification recipe (address -> tag/regex) on each document.

Use this to back-fill or correct the `pool` field after pool definitions
change — e.g., after adding Binance BCH to pool_definitions.json.

Example:
    python reidentify_pool_blocks.py \
        --mongo-uri "mongodb://mongouser:mongopassword@localhost:27017" \
        --pool-file ../backend/pool_definitions.json \
        --pool-filter "Binance Pool" \
        --chunk-size 200 \
        --dry-run
"""

import argparse
import json
import logging
import re
import sys
import time
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError, PyMongoError


LOG = logging.getLogger("reidentify-pool-blocks")


# ---------------------------------------------------------------------------
# Pool identification recipe
# Mirrors backend/analytics/pool_identification.py — kept inline so this
# script has no hard dependency on the backend package.
# ---------------------------------------------------------------------------

def _identify_by_address(
    pools: Dict[str, Dict[str, Any]], coinbase_addresses: List[str]
) -> Dict[str, Any]:
    if not coinbase_addresses:
        return {}
    for pool_id, pool in pools.items():
        for addr in coinbase_addresses:
            if addr in pool.get("addresses", []):
                return {
                    "id": pool_id,
                    "name": pool.get("name"),
                    "slug": pool.get("slug", (pool.get("name") or "").lower().replace(" ", "-")),
                    "link": pool.get("link"),
                    "identification_method": "address",
                }
    return {}


def _identify_by_tag(
    pools: Dict[str, Dict[str, Any]], coinbase_hex: str
) -> Dict[str, Any]:
    if not coinbase_hex:
        return {}
    try:
        text = bytes.fromhex(coinbase_hex).decode("utf-8", errors="replace").replace("\n", "")
        for pool_id, pool in pools.items():
            for tag in pool.get("tags", []):
                if tag in text:
                    return {
                        "id": pool_id,
                        "name": pool.get("name"),
                        "slug": pool.get("slug", (pool.get("name") or "").lower().replace(" ", "-")),
                        "link": pool.get("link"),
                        "identification_method": "tag",
                    }
            for pattern in pool.get("regexes", []):
                if re.search(pattern, text, re.IGNORECASE):
                    return {
                        "id": pool_id,
                        "name": pool.get("name"),
                        "slug": pool.get("slug", (pool.get("name") or "").lower().replace(" ", "-")),
                        "link": pool.get("link"),
                        "identification_method": "regex",
                    }
    except Exception:
        pass
    return {}


def identify_pool(
    pools: Dict[str, Dict[str, Any]],
    coinbase_hex: str,
    coinbase_addresses: List[str],
) -> Dict[str, Any]:
    result = _identify_by_address(pools, coinbase_addresses)
    if result:
        return result
    return _identify_by_tag(pools, coinbase_hex)


# ---------------------------------------------------------------------------
# Pool definition loading
# ---------------------------------------------------------------------------

def load_pools_from_file(path: str) -> Dict[str, Dict[str, Any]]:
    with open(path, "r") as f:
        data = json.load(f)
    return {p.get("id"): p for p in data}


def load_pools_from_url(url: str) -> Dict[str, Dict[str, Any]]:
    import requests
    resp = requests.get(url, headers={"User-Agent": "stratum-work/1.0"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {p.get("id"): p for p in data}


# ---------------------------------------------------------------------------
# Chunk processing
# ---------------------------------------------------------------------------

def process_chunk(
    collection,
    pools: Dict[str, Dict[str, Any]],
    low: int,
    high: int,
    pool_filter: Optional[str],
    dry_run: bool,
) -> Dict[str, int]:
    docs = list(
        collection.find({"height": {"$gte": low, "$lte": high}}).sort("height", 1)
    )
    stats = {"scanned": len(docs), "matched": 0, "updated": 0, "no_change": 0, "unidentified": 0}

    bulk_ops: List[UpdateOne] = []
    for doc in docs:
        coinbase_hex: str = doc.get("coinbase_script_sig", "") or ""

        # Extract existing coinbase addresses from the stored pool field if present
        pool_field = doc.get("pool") or {}
        existing_addresses: List[str] = []
        if isinstance(pool_field, dict):
            raw_addrs = pool_field.get("addresses", [])
            if isinstance(raw_addrs, list):
                existing_addresses = [str(a) for a in raw_addrs]

        identified = identify_pool(pools, coinbase_hex, existing_addresses)

        if not identified:
            stats["unidentified"] += 1
            continue

        name = identified.get("name", "")
        if pool_filter and name.lower() != pool_filter.lower():
            continue

        stats["matched"] += 1
        LOG.debug(
            "height=%d  pool=%s  method=%s",
            doc.get("height"),
            name,
            identified.get("identification_method"),
        )

        existing_name = pool_field.get("name") if isinstance(pool_field, dict) else None
        if existing_name == name:
            stats["no_change"] += 1
            continue

        if not dry_run:
            bulk_ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "pool.name": name,
                            "pool.slug": identified.get("slug"),
                            "pool.link": identified.get("link"),
                            "pool.identification_method": identified.get("identification_method"),
                        }
                    },
                )
            )
        stats["updated"] += 1

    if bulk_ops:
        try:
            collection.bulk_write(bulk_ops, ordered=False)
        except BulkWriteError as bwe:
            LOG.warning("Bulk write partial error: %s", bwe.details)

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    client = MongoClient(args.mongo_uri)
    db = client[args.db_name]
    collection = db[args.collection]

    if args.pool_file:
        LOG.info("Loading pool definitions from file: %s", args.pool_file)
        pools = load_pools_from_file(args.pool_file)
    elif args.pool_url:
        LOG.info("Loading pool definitions from URL: %s", args.pool_url)
        pools = load_pools_from_url(args.pool_url)
    else:
        LOG.error("Provide --pool-file or --pool-url")
        sys.exit(1)

    LOG.info("Loaded %d pool definitions", len(pools))

    height_filter = {"height": {"$exists": True, "$type": "number"}}

    if args.start_height is None:
        doc = collection.find_one(height_filter, {"height": 1}, sort=[("height", 1)])
        start_height = doc["height"] if doc else 0
    else:
        start_height = args.start_height

    if args.end_height is None:
        doc = collection.find_one(height_filter, {"height": 1}, sort=[("height", -1)])
        end_height = doc["height"] if doc else start_height
    else:
        end_height = args.end_height

    LOG.info(
        "Heights [%d..%d], chunk_size=%d, pool_filter=%r, dry_run=%s",
        start_height, end_height, args.chunk_size, args.pool_filter, args.dry_run,
    )

    totals: Dict[str, int] = {"scanned": 0, "matched": 0, "updated": 0, "no_change": 0, "unidentified": 0}
    chunk_idx = 0
    current = start_height

    while current <= end_height:
        low = current
        high = min(current + args.chunk_size - 1, end_height)
        LOG.info("Chunk %d  [%d..%d]", chunk_idx + 1, low, high)

        stats = process_chunk(collection, pools, low, high, args.pool_filter, args.dry_run)
        for k in totals:
            totals[k] += stats[k]

        LOG.info(
            "  scanned=%-5d  matched=%-5d  updated=%-5d  no_change=%-5d  unidentified=%d",
            stats["scanned"], stats["matched"], stats["updated"],
            stats["no_change"], stats["unidentified"],
        )

        chunk_idx += 1
        current = high + 1

        if args.sleep > 0 and current <= end_height:
            time.sleep(args.sleep)

    LOG.info(
        "Finished. %d chunks. scanned=%d  matched=%d  updated=%d  no_change=%d  unidentified=%d",
        chunk_idx,
        totals["scanned"], totals["matched"], totals["updated"],
        totals["no_change"], totals["unidentified"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run pool identification recipe on MongoDB blocks in height-ordered chunks."
    )
    parser.add_argument(
        "--mongo-uri", required=True,
        help="MongoDB connection URI (e.g., mongodb://user:pass@host:27017)",
    )
    parser.add_argument("--db-name", default="stratum-logger", help="Database name (default: stratum-logger)")
    parser.add_argument("--collection", default="blocks", help="Collection name (default: blocks)")
    parser.add_argument("--pool-file", default=None, help="Path to pool_definitions.json")
    parser.add_argument(
        "--pool-url",
        default=None,
        help="URL to fetch pool definitions JSON (e.g., mempool pools-v2.json)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=100,
        help="Number of block heights per chunk (default: 100)",
    )
    parser.add_argument("--start-height", type=int, default=None, help="First block height (default: min in DB)")
    parser.add_argument("--end-height", type=int, default=None, help="Last block height (default: max in DB)")
    parser.add_argument(
        "--pool-filter", default=None,
        help="Only update blocks identified as this pool name (case-insensitive)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and match without writing any updates to the database",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0,
        help="Seconds to sleep between chunks to reduce DB load (default: 0)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )
    run(args)
