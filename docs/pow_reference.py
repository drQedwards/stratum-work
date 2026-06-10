"""
Proof-of-Work reference — three stages after a mining.notify arrives.

Stage 1 : Build the 80-byte block header and solve the PoW puzzle
Stage 2 : Submit the winning share to the pool via mining.submit (stratum)
Stage 3 : Broadcast a raw transaction to mempool.space (BCH API)

NOTE: Python SHA-256d runs ~500 kH/s on a modern CPU.
      Real BCH difficulty requires ~300 EH/s network-wide.
      This code shows the mechanics; actual mining needs ASIC hardware.
"""

import hashlib
import socket
import json
import struct
import time
import requests


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def sha256d(data: bytes) -> bytes:
    """Bitcoin double-SHA256."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def bits_to_target(nbits_hex: str) -> int:
    """Convert compact nbits field to 256-bit integer target."""
    nbits = int(nbits_hex, 16)
    exponent = nbits >> 24
    mantissa  = nbits & 0x00FFFFFF
    return mantissa * (2 ** (8 * (exponent - 3)))


def build_merkle_root(coinbase_tx_hash: bytes, branches: list[str]) -> bytes:
    """Walk the merkle branch list to produce the merkle root."""
    current = coinbase_tx_hash
    for branch in branches:
        current = sha256d(current + bytes.fromhex(branch))
    return current


def build_coinbase_tx(coinbase1: str, extranonce1: str,
                      extranonce2: str, coinbase2: str) -> bytes:
    """Assemble the full coinbase transaction bytes from stratum fields."""
    return bytes.fromhex(coinbase1 + extranonce1 + extranonce2 + coinbase2)


def build_header(version: str, prev_hash: str, merkle_root: bytes,
                 ntime: str, nbits: str, nonce: int) -> bytes:
    """Pack the 80-byte block header."""
    return (
        bytes.fromhex(version)[::-1]       # version      (4 bytes LE)
        + bytes.fromhex(prev_hash)[::-1]   # prev_hash    (32 bytes LE)
        + merkle_root[::-1]                # merkle_root  (32 bytes LE)
        + bytes.fromhex(ntime)[::-1]       # ntime        (4 bytes LE)
        + bytes.fromhex(nbits)[::-1]       # nbits        (4 bytes LE)
        + struct.pack("<I", nonce)         # nonce        (4 bytes LE)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Solve the PoW puzzle
# ─────────────────────────────────────────────────────────────────────────────

def solve_pow(notify: dict, extranonce1: str, extranonce2_length: int,
              max_nonces: int = 2**32) -> dict | None:
    """
    Iterate nonces until the block hash is below the target.

    Parameters
    ----------
    notify            : the mining.notify params dict
    extranonce1       : assigned by pool during mining.subscribe
    extranonce2_length: byte length assigned by pool
    max_nonces        : cap for this demo (full range is 2^32 = 4 billion)

    Returns a dict with the winning fields, or None if no solution found.
    """
    params       = notify["params"]
    job_id       = params[0]
    prev_hash    = params[1]
    coinbase1    = params[2]
    coinbase2    = params[3]
    branches     = params[4]
    version      = params[5]
    nbits        = params[6]
    ntime        = params[7]

    target = bits_to_target(nbits)
    print(f"[PoW] target  = 0x{target:064x}")
    print(f"[PoW] job_id  = {job_id}  nbits = {nbits}")

    # extranonce2 is miner-controlled — increment it to extend the search space
    extranonce2 = "00" * extranonce2_length

    coinbase_tx   = build_coinbase_tx(coinbase1, extranonce1, extranonce2, coinbase2)
    coinbase_hash = sha256d(coinbase_tx)
    merkle_root   = build_merkle_root(coinbase_hash, branches)

    start = time.time()
    for nonce in range(max_nonces):
        header     = build_header(version, prev_hash, merkle_root, ntime, nbits, nonce)
        block_hash = sha256d(header)

        # Bitcoin stores the hash in little-endian; compare as integer
        hash_int = int.from_bytes(block_hash[::-1], "big")

        if hash_int < target:
            elapsed = time.time() - start
            print(f"\n[PoW] ✓ Solution found! nonce=0x{nonce:08x}  "
                  f"hash=0x{hash_int:064x}")
            print(f"[PoW]   {nonce:,} hashes in {elapsed:.2f}s  "
                  f"({nonce / elapsed / 1e3:.1f} kH/s)")
            return {
                "job_id":      job_id,
                "extranonce2": extranonce2,
                "ntime":       ntime,
                "nonce":       f"{nonce:08x}",
                "header_hex":  header.hex(),
                "hash_hex":    block_hash[::-1].hex(),
            }

        if nonce % 500_000 == 0 and nonce:
            elapsed = time.time() - start
            print(f"[PoW] {nonce:>12,} hashes  {nonce/elapsed/1e3:.0f} kH/s  "
                  f"(best: 0x{hash_int:016x}...)")

    print("[PoW] No solution in search range — would need to roll extranonce2.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Submit the winning share to the pool (stratum mining.submit)
# ─────────────────────────────────────────────────────────────────────────────

def submit_share(pool_host: str, pool_port: int,
                 worker: str, solution: dict,
                 extranonce1: str, extranonce2_length: int) -> dict:
    """
    Open a stratum connection, subscribe + authorize, then send mining.submit.

    In production this reuses the existing long-lived connection; here we
    open a fresh one for clarity.
    """
    s = socket.socket()
    s.settimeout(30)
    s.connect((pool_host, pool_port))
    print(f"\n[Submit] Connected to {pool_host}:{pool_port}")

    def rpc(sock, method, params, req_id):
        msg = json.dumps({"id": req_id, "method": method, "params": params}) + "\n"
        sock.sendall(msg.encode())
        buf = b""
        while b"\n" not in buf:
            buf += sock.recv(4096)
        return json.loads(buf.split(b"\n")[0])

    # Re-subscribe so the pool associates our session
    sub = rpc(s, "mining.subscribe", [], 1)
    print(f"[Submit] subscribe → extranonce1={sub['result'][-2]}")

    auth = rpc(s, "mining.authorize", [worker, "x"], 2)
    print(f"[Submit] authorize → result={auth['result']}")

    # ── The actual submit ──
    submit_params = [
        worker,                   # [0] worker name
        solution["job_id"],       # [1] job_id from mining.notify
        solution["extranonce2"],  # [2] extranonce2 we chose
        solution["ntime"],        # [3] ntime (may be rolled slightly)
        solution["nonce"],        # [4] winning nonce as 8-char hex
    ]
    resp = rpc(s, "mining.submit", submit_params, 3)
    s.close()

    if resp.get("result") is True:
        print(f"[Submit] ✓ Share ACCEPTED by pool")
    else:
        print(f"[Submit] ✗ Share rejected: {resp.get('error')}")
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Broadcast a raw transaction to mempool.space (BCH)
# ─────────────────────────────────────────────────────────────────────────────

def broadcast_transaction(raw_tx_hex: str, network: str = "bch") -> str:
    """
    Push a fully-signed raw transaction to the mempool.space BCH API.

    Parameters
    ----------
    raw_tx_hex : complete serialized transaction in hex
                 (must be signed with the correct private key)
    network    : "bch" for Bitcoin Cash mainnet

    Returns the txid string on success, raises on HTTP error.

    The pool pays the coinbase reward directly to the address you
    configured in your Binance Pool account — this endpoint is for
    spending outputs from your wallet, not for block submission.
    """
    url = f"https://{network}.mempool.space/api/tx"
    print(f"\n[Broadcast] POST {url}")
    print(f"[Broadcast] raw_tx ({len(raw_tx_hex)//2} bytes): {raw_tx_hex[:64]}...")

    resp = requests.post(url, data=raw_tx_hex,
                         headers={"Content-Type": "text/plain"}, timeout=30)
    resp.raise_for_status()
    txid = resp.text.strip()
    print(f"[Broadcast] ✓ Accepted  txid = {txid}")
    return txid


# ─────────────────────────────────────────────────────────────────────────────
# Demo — wire all three stages together using the mock notify from the workflow
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import time

    # These come from the mining.subscribe + mining.notify in the collector workflow
    EXTRANONCE1       = "deadbeef"
    EXTRANONCE2_LEN   = 4
    POOL_HOST         = "bch.poolbinance.com"
    POOL_PORT         = 3333
    WORKER            = "developer1.001"

    # Artificially low target so Python can find a solution quickly
    # (real BCH target is ~1/quintillion of the full 256-bit space)
    DEMO_NBITS = "207fffff"

    mock_notify = {
        "params": [
            "4a1b",                                          # job_id
            "00000000000000004a9e7b4a" + "00" * 20,         # prev_hash
            "03a0bb0d2f42696e616e63652f",                   # coinbase1
            "ffffffff",                                      # coinbase2
            [
                "c5d2460186f7233c927e7db2dcc703c0e500b653"
                "ca82273b7bfad8045d85a470",
                "e3b0c44298fc1c149afbf4c8996fb924"
                "27ae41e4649b934ca495991b7852b855",
            ],
            "20000000",                                      # version
            DEMO_NBITS,                                      # nbits (easy target)
            hex(int(time.time()))[2:],                       # ntime
            True,                                            # clean_jobs
        ]
    }

    print("=" * 60)
    print("Stage 1 — Solve PoW")
    print("=" * 60)
    solution = solve_pow(mock_notify, EXTRANONCE1, EXTRANONCE2_LEN)

    if solution:
        print(f"\n  header : {solution['header_hex']}")
        print(f"  hash   : {solution['hash_hex']}")
        print(f"  nonce  : {solution['nonce']}")

        # Stage 2 — would connect to bch.poolbinance.com:3333 and submit
        # Uncomment with real pool credentials:
        #
        # print("\n" + "=" * 60)
        # print("Stage 2 — Submit share to Binance BCH pool")
        # print("=" * 60)
        # submit_share(POOL_HOST, POOL_PORT, WORKER, solution,
        #              EXTRANONCE1, EXTRANONCE2_LEN)

        # Stage 3 — sign a spending tx with Bitcore and broadcast to mempool.space
        #
        # Prerequisites (Node.js):
        #   npm install bitcore-lib-cash
        #
        # Then generate + sign in Node:
        #
        #   const bitcore = require("bitcore-lib-cash");
        #   const { PrivateKey, Address, Transaction } = bitcore;
        #
        #   const privKey = PrivateKey.fromWIF("<your WIF private key>");
        #   const address = privKey.toAddress();
        #
        #   // UTXOs come from your Binance Pool payout address:
        #   //   GET https://bch.mempool.space/api/address/<addr>/utxo
        #   const utxo = {
        #     txId:        "<unspent txid>",
        #     outputIndex: 0,
        #     address:     address.toString(),
        #     script:      bitcore.Script(address).toHex(),
        #     satoshis:    <amount in satoshis>,
        #   };
        #
        #   const tx = new Transaction()
        #     .from(utxo)
        #     .to("<recipient BCH address>", utxo.satoshis - 500)  // 500 sat fee
        #     .change(address)
        #     .sign(privKey);
        #
        #   const rawHex = tx.serialize();
        #
        # Then pass rawHex here:
        #
        # print("\n" + "=" * 60)
        # print("Stage 3 — Broadcast transaction to mempool.space")
        # print("=" * 60)
        # SIGNED_TX_HEX = rawHex   # from tx.serialize() above
        # txid = broadcast_transaction(SIGNED_TX_HEX, network="bch")
        # print(f"  View: https://bch.mempool.space/tx/{txid}")

        print("\n[Done] Stages 2 and 3 are commented out — "
              "supply real pool credentials and a signed tx to activate them.")
