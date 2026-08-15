import { NextRequest, NextResponse } from 'next/server';
import { S3PresignedUrlGenerator } from '@/lib/s3-signer';

/**
 * API Route to generate presigned URLs for iDriveE2 files
 * Runs server-side - credentials never exposed to browser
 */

// Initialize S3 signer with server-side env vars (no NEXT_PUBLIC_ prefix)
const s3Signer = new S3PresignedUrlGenerator({
  endpoint: process.env.IDRIVEE2_ENDPOINT_URL || '',
  region: process.env.IDRIVEE2_REGION || 'us-east-1',
  bucket: process.env.IDRIVEE2_BUCKET_NAME || '',
  accessKeyId: process.env.IDRIVEE2_ACCESS_KEY_ID || '',
  secretAccessKey: process.env.IDRIVEE2_SECRET_ACCESS_KEY || '',
});

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const fileKey = searchParams.get('file_key');

    if (!fileKey) {
      return NextResponse.json(
        { error: 'file_key parameter is required' },
        { status: 400 }
      );
    }

    // Generate presigned URL (expires in 1 hour)
    const presignedUrl = await s3Signer.generatePresignedUrl(fileKey, 3600);

    return NextResponse.json({ url: presignedUrl });
  } catch (error: any) {
    console.error('Failed to generate presigned URL:', error);
    return NextResponse.json(
      { error: 'Failed to generate presigned URL', details: error.message },
      { status: 500 }
    );
  }
}
