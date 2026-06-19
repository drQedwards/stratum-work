// Shared helpers: SparkScan/Flashnet reads, bech32m, quote math.
// Pure read/compute — no signing. Safe to run without any keys.

export const SPARKSCAN = "https://api.sparkscan.io";
export const FLASHNET = "https://api.flashnet.xyz";
export const NETWORK = "MAINNET";

// Canonical asset ids
export const BTC_ASSET =
  "020202020202020202020202020202020202020202020202020202020202020202";
export const TOKENS = {
  QCHAINS: "0c5dd7c18cdafcb3002550cb72c5ff30a3f6822dbb588fa68119ab9d793ad91c",
  DRQ: "8ece53d2adc389d842b7a03bc1f258259945eb556a98b5f7d9e855568e1f11ea",
  USDB: "3206c93b24a4d18ea19d0a9a213204af2c7e74a6d16c7535cc5d33eca4ad1eca",
};

export const WALLETS = {
  QCHAINS_TREASURY:
    "spark1pgssxqqs6phdx7nmrc6vz0yh8h5f6lq3awk8hhw7sqs4ma9zjh4a3l7cknx55x",
  DRQ_WALLET:
    "spark1pgss92h8z4cpepy34nzvx2nf2hyjp5s6977eryhuxfglndp06afxg2un0s0anh",
};

const APIKEY = process.env.SPARKSCAN_API_KEY || "";

async function jget(url, headers = {}) {
  const r = await fetch(url, {
    headers: { "User-Agent": "tx-workflow/1.0", Accept: "application/json", ...headers },
  });
  if (!r.ok) throw new Error(`GET ${url} -> ${r.status} ${await r.text()}`);
  return r.json();
}

// ---- bech32m (btkn address) encoder, for SparkScan token lookups ----
const CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
function polymod(values) {
  const GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  let chk = 1;
  for (const v of values) {
    const b = chk >> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ v;
    for (let i = 0; i < 5; i++) if ((b >> i) & 1) chk ^= GEN[i];
  }
  return chk >>> 0;
}
function hrpExpand(h) {
  const out = [];
  for (const c of h) out.push(c.charCodeAt(0) >> 5);
  out.push(0);
  for (const c of h) out.push(c.charCodeAt(0) & 31);
  return out;
}
function convert(data, from, to) {
  let acc = 0, bits = 0;
  const out = [];
  for (const v of data) {
    acc = (acc << from) | v;
    bits += from;
    while (bits >= to) { bits -= to; out.push((acc >> bits) & ((1 << to) - 1)); }
  }
  if (bits) out.push((acc << (to - bits)) & ((1 << to) - 1));
  return out;
}
export function btknAddress(hexId) {
  const bytes = Buffer.from(hexId, "hex");
  const data = convert([...bytes], 8, 5);
  const chk = polymod([...hrpExpand("btkn"), ...data, 0, 0, 0, 0, 0, 0]) ^ 0x2bc830a3;
  let out = "btkn1";
  for (const d of data) out += CHARSET[d];
  for (let i = 0; i < 6; i++) out += CHARSET[(chk >> (5 * (5 - i))) & 31];
  return out;
}

// ---- SparkScan reads ----
export function addressSummary(addr) {
  return jget(`${SPARKSCAN}/v1/address/${addr}?network=${NETWORK}`, { "x-api-key": APIKEY });
}

// ---- Flashnet pool reads ----
export async function poolFor(tokenHex) {
  const d = await jget(
    `${FLASHNET}/v1/pools?network=${NETWORK}&assetAAddress=${tokenHex}&limit=20`
  );
  return (d.pools || [])[0] || null;
}
export async function bestUsdbPool() {
  const d = await jget(
    `${FLASHNET}/v1/pools?network=${NETWORK}&assetBAddress=${TOKENS.USDB}&limit=20`
  );
  const pools = d.pools || [];
  pools.sort((a, b) => Number(b.assetAReserve || 0) - Number(a.assetAReserve || 0));
  return pools[0] || null;
}

// ---- constant-product / single-sided quote (x*y=k with fee) ----
export function quoteOut(reserveIn, reserveOut, amountIn, feeBps) {
  const inWithFee = (BigInt(amountIn) * BigInt(10000 - feeBps)) / 10000n;
  return (BigInt(reserveOut) * inWithFee) / (BigInt(reserveIn) + inWithFee);
}

export const fmt = (n, dec = 8) => {
  const s = BigInt(n).toString().padStart(dec + 1, "0");
  return `${s.slice(0, -dec)}.${s.slice(-dec)}`;
};
