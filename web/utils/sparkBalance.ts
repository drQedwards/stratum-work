import { SparkReadonlyClient } from '@buildonspark/spark-sdk';

export async function fetchSparkBalance(sparkAddress: string): Promise<bigint> {
  const client = SparkReadonlyClient.createPublic({ network: 'MAINNET' });
  return client.getAvailableBalance(sparkAddress);
}
