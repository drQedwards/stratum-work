import { NextRequest, NextResponse } from 'next/server';
import { fetchSparkGossip } from '@/utils/sparkGossip';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const address = searchParams.get('address');
  const limit = parseInt(searchParams.get('limit') ?? '25', 10);
  const offset = parseInt(searchParams.get('offset') ?? '0', 10);

  if (!address) {
    return NextResponse.json({ error: 'Missing address parameter' }, { status: 400 });
  }

  try {
    const data = await fetchSparkGossip(address, limit, offset);
    return NextResponse.json(data);
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
