import { NextRequest, NextResponse } from 'next/server';
import { fetchSparkBalance } from '@/utils/sparkBalance';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const address = searchParams.get('address');

  if (!address) {
    return NextResponse.json({ error: 'Missing address parameter' }, { status: 400 });
  }

  try {
    const sats = await fetchSparkBalance(address);
    return NextResponse.json({ address, sats: sats.toString() });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
