import { SparkReadonlyClient } from '@buildonspark/spark-sdk';

export interface GossipResult {
  transfers: SerializedTransfer[];
  offset: number;
}

interface SerializedTransfer {
  id: string;
  status: number;
  totalValue: number;
  type: number;
  createdTime: string | null;
  updatedTime: string | null;
  sparkInvoice: string;
}

type RawTransfer = Awaited<ReturnType<SparkReadonlyClient['getTransfers']>>['transfers'][number];

function serializeTransfer(t: RawTransfer): SerializedTransfer {
  return {
    id: t.id,
    status: t.status,
    totalValue: t.totalValue,
    type: t.type,
    createdTime: t.createdTime?.toISOString() ?? null,
    updatedTime: t.updatedTime?.toISOString() ?? null,
    sparkInvoice: t.sparkInvoice,
  };
}

export async function fetchSparkGossip(
  sparkAddress: string,
  limit = 25,
  offset = 0,
): Promise<GossipResult> {
  const client = SparkReadonlyClient.createPublic({ network: 'MAINNET' });
  const result = await client.getTransfers({ sparkAddress, limit, offset });
  return {
    transfers: result.transfers.map(serializeTransfer),
    offset: result.offset,
  };
}
