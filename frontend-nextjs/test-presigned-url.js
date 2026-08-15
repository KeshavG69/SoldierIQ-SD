/**
 * Test script to generate presigned URL for iDriveE2
 * Uses AWS SDK (boto3-compatible)
 * Run with: node test-presigned-url.js
 */

const { S3Client, GetObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');

// Configuration from .env.local
const config = {
  endpoint: 'https://s3.us-west-1.idrivee2.com',
  region: 'us-east-1',
  bucket: 'soldieriq-documents',
  accessKeyId: 'vApbrjFCnCRtY62obpPY',
  secretAccessKey: 'VHJ32pJoRRTCkrT6MsdAf5aSQlWviG506Lnia2UM',
};

// File to test
const objectKey = 'test_videos/Instructional VSAT Setup.mp4';
const expiresIn = 3600; // 1 hour

async function generatePresignedUrl() {
  // Initialize S3 client (just like Python's boto3)
  const s3Client = new S3Client({
    region: config.region,
    endpoint: config.endpoint,
    credentials: {
      accessKeyId: config.accessKeyId,
      secretAccessKey: config.secretAccessKey,
    },
    forcePathStyle: true, // Required for S3-compatible services
  });

  const command = new GetObjectCommand({
    Bucket: config.bucket,
    Key: objectKey,
  });

  const presignedUrl = await getSignedUrl(s3Client, command, {
    expiresIn,
  });

  return presignedUrl;
}

// Generate and display URL
(async () => {
  try {
    console.log('\n🔐 Generating presigned URL for iDriveE2 (boto3-compatible)...\n');
    console.log('Configuration:');
    console.log(`  Endpoint: ${config.endpoint}`);
    console.log(`  Bucket: ${config.bucket}`);
    console.log(`  Region: ${config.region}`);
    console.log(`  Object Key: ${objectKey}`);
    console.log(`  Expires In: ${expiresIn} seconds (1 hour)\n`);

    const presignedUrl = await generatePresignedUrl();

    console.log('✅ Presigned URL generated:\n');
    console.log(presignedUrl);
    console.log('\n📺 To play video clip from 10s to 25s, add: #t=10,25');
    console.log(`${presignedUrl}#t=10,25`);
    console.log('\n');
  } catch (error) {
    console.error('❌ Error generating presigned URL:', error);
  }
})();
