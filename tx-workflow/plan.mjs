// Read-only planner: pulls live balances + pool reserves, computes the
// QCHAINS/DRQ -> BTC -> USDB route and the deliverable USDB amount.
// No keys required. Run: SPARKSCAN_API_KEY=... node plan.mjs

import {
  WALLETS, TOKENS, BTC_ASSET, addressSummary, poolFor, bestUsdbPool,
  quoteOut, fmt, btknAddress,
} from "./lib.mjs";

function reserves(pool) {
  const tokenIsA = pool.assetBAddress === BTC_ASSET;
  return {
    tokenReserve: tokenIsA ? pool.assetAReserve : pool.assetBReserve,
    btcReserve: tokenIsA ? pool.assetBReserve : pool.assetAReserve,
    feeBps: (pool.lpFeeBps || 0) + (pool.hostFeeBps || 0),
  };
}

async function legTokenToBtc(name, tokenHex, holderAddr) {
  const pool = await poolFor(tokenHex);
  const sum = await addressSummary(holderAddr);
  const tok = (sum.tokens || []).find(
    (t) => btknAddress(tokenHex) === t.tokenAddress
  );
  const held = tok ? BigInt(tok.balance) : 0n;
  if (!pool) return { name, held, satsOut: 0n, note: "no pool" };
  const { tokenReserve, btcReserve, feeBps } = reserves(pool);
  const satsOut = quoteOut(tokenReserve, btcReserve, held, feeBps);
  return {
    name, held, satsOut, feeBps,
    btcReserve: BigInt(btcReserve),
    note: `pool ${pool.curveType} fee ${feeBps}bps, BTC reserve ${btcReserve} sats`,
  };
}

(async () => {
  console.log("=== Live route plan: QCHAINS/DRQ -> BTC -> USDB ===\n");

  const qc = await legTokenToBtc("QCHAINS", TOKENS.QCHAINS, WALLETS.QCHAINS_TREASURY);
  const drq = await legTokenToBtc("DRQ", TOKENS.DRQ, WALLETS.DRQ_WALLET);

  for (const leg of [qc, drq]) {
    console.log(`${leg.name}:`);
    console.log(`  holding         ${fmt(leg.held)} ${leg.name}`);
    console.log(`  -> BTC out      ${leg.satsOut} sats  (capped by reserve)`);
    console.log(`  ${leg.note}\n`);
  }

  const qcSum = await addressSummary(WALLETS.QCHAINS_TREASURY);
  const drqSum = await addressSummary(WALLETS.DRQ_WALLET);
  const freeSats =
    BigInt(qcSum.balance?.btcSoftBalanceSats || 0) +
    BigInt(drqSum.balance?.btcSoftBalanceSats || 0);

  const totalSats = qc.satsOut + drq.satsOut + freeSats;
  console.log(`free wallet BTC   ${freeSats} sats`);
  console.log(`TOTAL BTC budget  ${totalSats} sats (${fmt(totalSats)} BTC)\n`);

  const usdbPool = await bestUsdbPool();
  if (!usdbPool) { console.log("No USDB pool found."); return; }
  const usdbTokenIsB = usdbPool.assetBAddress === TOKENS.USDB;
  const btcRes = usdbTokenIsB ? usdbPool.assetAReserve : usdbPool.assetBReserve;
  const usdbRes = usdbTokenIsB ? usdbPool.assetBReserve : usdbPool.assetAReserve;
  const feeBps = (usdbPool.lpFeeBps || 0) + (usdbPool.hostFeeBps || 0);
  const usdbOut = quoteOut(btcRes, usdbRes, totalSats, feeBps);

  console.log(`USDB pool ${usdbPool.curveType} fee ${feeBps}bps`);
  console.log(`  BTC reserve   ${btcRes} sats`);
  console.log(`  USDB reserve  ${fmt(usdbRes)} USDB`);
  console.log(`\n>>> DELIVERABLE: ${fmt(usdbOut)} USDB  (spending ${totalSats} sats)`);
})().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
