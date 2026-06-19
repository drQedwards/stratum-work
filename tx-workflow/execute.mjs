// Sweep + swap executor.
// Signing requires the Spark SDK + YOUR mnemonic, supplied locally via env:
//   SPARK_MNEMONIC="word1 word2 ... word12"   (use your NEW wallet)
//   SPARKSCAN_API_KEY=...
//   CONFIRM=YES                                 (final safety gate)
//   DEST_SPARK_ADDRESS=spark1...                (NEW wallet to sweep into)
//
// Without SPARK_MNEMONIC + CONFIRM=YES this runs as a DRY RUN.

import { WALLETS, TOKENS } from "./lib.mjs";

const MNEMONIC = process.env.SPARK_MNEMONIC || "";
const CONFIRM = process.env.CONFIRM === "YES";
const DEST = process.env.DEST_SPARK_ADDRESS || "";
const DRY = !(MNEMONIC && CONFIRM);

function banner(msg) { console.log("\n" + "=".repeat(60) + "\n" + msg + "\n" + "=".repeat(60)); }

async function main() {
  banner(DRY ? "DRY RUN — no transactions will be signed or broadcast"
             : "LIVE EXECUTION");

  if (DRY) {
    console.log(`
Guards not satisfied for live run:
  SPARK_MNEMONIC set : ${MNEMONIC ? "yes" : "NO"}
  CONFIRM=YES        : ${CONFIRM ? "yes" : "NO"}
  DEST address       : ${DEST || "(unset)"}

Planned actions (in order) once guards are satisfied:
  1. Initialize SparkWallet from SPARK_MNEMONIC (network MAINNET)
  2. Swap entire QCHAINS holding -> BTC on its Flashnet bonding pool
  3. Swap entire DRQ holding -> BTC on its Flashnet bonding pool
  4. Swap total BTC -> USDB on the deep Flashnet V3 pool
  5. (optional) sweep resulting USDB + dust BTC to DEST_SPARK_ADDRESS

No keys present — stopping here (expected safe outcome).
`);
    return;
  }

  // ---- LIVE PATH ----
  const { SparkWallet } = await import("@buildonspark/spark-sdk").catch(() => {
    throw new Error("Install the signer: npm install @buildonspark/spark-sdk");
  });

  const { wallet } = await SparkWallet.initialize({
    mnemonicOrSeed: MNEMONIC,
    options: { network: "MAINNET" },
  });
  const me = await wallet.getSparkAddress();
  console.log("Loaded wallet:", me);

  const bal = await wallet.getBalance();
  console.log("Balance:", JSON.stringify(bal, null, 2));

  async function swap(fromAsset, toAsset, amount, label) {
    console.log(`\nSwapping ${label}: amount=${amount}`);
    const res = await wallet.swap({
      fromTokenAddress: fromAsset,
      toTokenAddress: toAsset,
      amount,
      slippageBps: 100,
    });
    console.log("  tx:", res?.id || JSON.stringify(res));
    return res;
  }

  // Tokens -> BTC
  const tokens = bal.tokenBalances || [];
  for (const { tokenAddress, balance } of tokens) {
    if (tokenAddress === TOKENS.QCHAINS && BigInt(balance) > 0n) {
      await swap(tokenAddress, "btc", balance, "QCHAINS->BTC");
    }
    if (tokenAddress === TOKENS.DRQ && BigInt(balance) > 0n) {
      await swap(tokenAddress, "btc", balance, "DRQ->BTC");
    }
  }

  // BTC -> USDB
  const btcBal = bal.btcBalance || bal.balance?.btcSoftBalanceSats || 0;
  if (BigInt(btcBal) > 0n) {
    await swap("btc", TOKENS.USDB, btcBal, "BTC->USDB");
  }

  // Sweep to new wallet
  if (DEST) {
    console.log(`\nSweeping all to ${DEST}`);
    await wallet.transferTokens?.({ to: DEST }).catch((e) => console.warn("sweep:", e.message));
  }

  console.log("\nDone.");
}

main().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
