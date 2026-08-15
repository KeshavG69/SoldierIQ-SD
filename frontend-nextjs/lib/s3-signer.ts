/**
 * S3 Presigned URL Generator using AWS SDK
 * Compatible with iDriveE2 (boto3-compatible)
 * Runs server-side only - credentials never exposed to browser
 */

import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

interface S3Config {
  endpoint: string;
  region: string;
  bucket: string;
  accessKeyId: string;
  secretAccessKey: string;
}

export class S3PresignedUrlGenerator {
  private s3Client: S3Client;
  private bucket: string;

  constructor(config: S3Config) {
    this.bucket = config.bucket;

    // Initialize S3 client with iDriveE2 endpoint
    this.s3Client = new S3Client({
      region: config.region,
      endpoint: config.endpoint,
      credentials: {
        accessKeyId: config.accessKeyId,
        secretAccessKey: config.secretAccessKey,
      },
      forcePathStyle: true, // Required for S3-compatible services like iDriveE2
    });
  }

  /**
   * Generate a presigned URL for an S3 object
   */
  async generatePresignedUrl(
    objectKey: string,
    expiresIn: number = 3600
  ): Promise<string> {
    const command = new GetObjectCommand({
      Bucket: this.bucket,
      Key: objectKey,
    });

    const presignedUrl = await getSignedUrl(this.s3Client, command, {
      expiresIn,
    });

    return presignedUrl;
  }
}
