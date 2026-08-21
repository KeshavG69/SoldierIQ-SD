"""
iDrive E2 Storage Client
S3-compatible cloud storage using aioboto3 for async operations
"""

import aioboto3
import boto3
from typing import Optional, BinaryIO, List, Dict, Any
from botocore.exceptions import ClientError
from app.settings import settings
from app.logger import logger


class IDriveE2Client:
    """Client for iDrive E2 cloud storage operations"""

    def __init__(self):
        """Initialize iDrive E2 client with aioboto3 and boto3"""
        self.endpoint_url = settings.IDRIVEE2_ENDPOINT_URL
        self.access_key = settings.IDRIVEE2_ACCESS_KEY_ID
        self.secret_key = settings.IDRIVEE2_SECRET_ACCESS_KEY
        self.bucket_name = settings.IDRIVEE2_BUCKET_NAME

        # Configure for iDrive E2 compatibility (disable checksums)
        from botocore.config import Config
        self.config = Config(
            signature_version='s3v4',
            s3={
                'payload_signing_enabled': False,
                'addressing_style': 'path'
            }
        )

        # Initialize aioboto3 session (async)
        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name='us-east-1'
        )

        # Initialize boto3 client (sync) with disabled threading for Celery compatibility
        from botocore.config import Config as BotoConfig
        sync_config = BotoConfig(
            signature_version='s3v4',
            s3={
                'payload_signing_enabled': False,
                'addressing_style': 'path'
            },
            max_pool_connections=1,  # Minimize connection pool
            use_dualstack_endpoint=False
        )

        self.sync_client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name='us-east-1',
            config=sync_config
        )

        logger.info(f"✅ iDrive E2 client initialized for bucket: {self.bucket_name}")

    def cleanup(self):
        """Clean up boto3 client resources and thread pools"""
        try:
            if hasattr(self, 'sync_client') and self.sync_client:
                # Close the boto3 client's connection pool
                self.sync_client.close()
                logger.info("✅ Closed boto3 sync client")
        except Exception as e:
            logger.warning(f"Error cleaning up IDriveE2 client: {str(e)}")

    async def upload_file(
        self,
        file_obj: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file to iDrive E2 storage (async)

        Args:
            file_obj: File object to upload
            object_name: S3 object name (key) in the bucket
            content_type: MIME type of the file

        Returns:
            str: Object key (not URL since bucket is private)

        Raises:
            Exception: If upload fails
        """
        try:
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type

            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                # Upload without checksum validation (iDrive E2 compatibility)
                await client.upload_fileobj(
                    file_obj,
                    self.bucket_name,
                    object_name,
                    ExtraArgs=extra_args
                )

            logger.info(f"✅ File uploaded successfully: {object_name}")
            return object_name

        except ClientError as e:
            logger.error(f"❌ Failed to upload file {object_name}: {str(e)}")
            raise Exception(f"Failed to upload file: {str(e)}")

    def upload_file_sync(
        self,
        file_obj: BinaryIO,
        object_name: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file to iDrive E2 storage (sync) without threading

        Args:
            file_obj: File object to upload
            object_name: S3 object name (key) in the bucket
            content_type: MIME type of the file

        Returns:
            str: Object key (not URL since bucket is private)

        Raises:
            Exception: If upload fails
        """
        try:
            # Read file content into memory
            file_content = file_obj.read()

            # Use put_object instead of upload_fileobj to avoid TransferManager threading
            put_args = {'Body': file_content}
            if content_type:
                put_args['ContentType'] = content_type

            self.sync_client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                **put_args
            )

            logger.info(f"✅ File uploaded successfully (sync): {object_name}")
            return object_name

        except ClientError as e:
            logger.error(f"❌ Failed to upload file {object_name}: {str(e)}")
            raise Exception(f"Failed to upload file: {str(e)}")

    # Download one file in 16MB byte-range chunks, each retried
    # independently. A single streaming GET of a large object was failing
    # mid-stream ("Not enough data to satisfy content length header") and
    # stalling — same fragility as a single-PUT upload. Ranged download means
    # a dropped connection only costs re-fetching that one chunk, and every
    # chunk is size-verified so a short read is caught and retried instead of
    # silently returning a truncated file to the ingestion pipeline.
    _DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
    _DOWNLOAD_MAX_RETRIES = 5
    _DOWNLOAD_CONCURRENCY = 6

    async def download_file(self, object_name: str) -> bytes:
        """
        Download a file from iDrive E2 storage (async), as multiple retried
        byte-range chunks fetched IN PARALLEL. This is both more robust (a
        dropped connection only costs re-fetching that one chunk, and each
        chunk is size-verified against a truncated read) and faster (iDrive
        appears to throttle per-connection, so concurrent ranges raise
        aggregate throughput).

        Args:
            object_name: S3 object name (key) in the bucket

        Returns:
            bytes: File content as bytes

        Raises:
            Exception: If the download can't complete after retries
        """
        import asyncio
        from botocore.config import Config

        # CRITICAL: give each chunk request an explicit connect/read timeout.
        # Without one, a stalled read hangs forever instead of erroring — so
        # the per-chunk retry below never gets a chance to fire.
        download_config = Config(
            signature_version='s3v4',
            s3={'payload_signing_enabled': False, 'addressing_style': 'path'},
            connect_timeout=15,
            read_timeout=90,
            max_pool_connections=self._DOWNLOAD_CONCURRENCY + 2,
            retries={'max_attempts': 1},  # we do our own ranged retries below
        )

        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=download_config
            ) as client:
                head = await client.head_object(Bucket=self.bucket_name, Key=object_name)
                total = head['ContentLength']

                buf = bytearray(total)
                sem = asyncio.Semaphore(self._DOWNLOAD_CONCURRENCY)

                ranges = [
                    (off, min(off + self._DOWNLOAD_CHUNK_BYTES, total) - 1)
                    for off in range(0, max(total, 1), self._DOWNLOAD_CHUNK_BYTES)
                ]

                async def fetch_range(start: int, end: int) -> None:
                    expected = end - start + 1
                    last_err = None
                    async with sem:
                        for attempt in range(1, self._DOWNLOAD_MAX_RETRIES + 1):
                            try:
                                resp = await client.get_object(
                                    Bucket=self.bucket_name,
                                    Key=object_name,
                                    Range=f"bytes={start}-{end}",
                                )
                                data = await resp['Body'].read()
                                if len(data) != expected:
                                    raise IOError(
                                        f"short read: got {len(data)} of {expected} bytes "
                                        f"for range {start}-{end}"
                                    )
                                buf[start:start + expected] = data
                                return
                            except Exception as e:  # noqa: BLE001 — retry any transient failure
                                last_err = e
                                if attempt < self._DOWNLOAD_MAX_RETRIES:
                                    await asyncio.sleep(min(2 ** attempt, 8))
                    raise Exception(
                        f"range {start}-{end} failed after "
                        f"{self._DOWNLOAD_MAX_RETRIES} attempts: {last_err}"
                    )

                if total > 0:
                    await asyncio.gather(*(fetch_range(s, e) for s, e in ranges))

            logger.info(f"✅ File downloaded successfully: {object_name} ({total} bytes)")
            return bytes(buf)

        except ClientError as e:
            logger.error(f"❌ Failed to download file {object_name}: {str(e)}")
            raise Exception(f"Failed to download file: {str(e)}")

    async def delete_file(self, object_name: str) -> bool:
        """
        Delete a file from iDrive E2 storage (async)

        Args:
            object_name: S3 object name (key) in the bucket

        Returns:
            bool: True if deletion was successful

        Raises:
            Exception: If deletion fails
        """
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                await client.delete_object(
                    Bucket=self.bucket_name,
                    Key=object_name
                )

            logger.info(f"✅ File deleted successfully: {object_name}")
            return True

        except ClientError as e:
            logger.error(f"❌ Failed to delete file {object_name}: {str(e)}")
            raise Exception(f"Failed to delete file: {str(e)}")

    def list_files(self, prefix: Optional[str] = None) -> list:
        """
        List files in the bucket

        Args:
            prefix: Optional prefix to filter objects

        Returns:
            list: List of object keys

        Raises:
            Exception: If listing fails
        """
        try:
            kwargs = {'Bucket': self.bucket_name}
            if prefix:
                kwargs['Prefix'] = prefix

            response = self.client.list_objects_v2(**kwargs)

            if 'Contents' not in response:
                return []

            files = [obj['Key'] for obj in response['Contents']]
            logger.info(f"✅ Listed {len(files)} files")
            return files

        except ClientError as e:
            logger.error(f"❌ Failed to list files: {str(e)}")
            raise Exception(f"Failed to list files: {str(e)}")

    def file_exists(self, object_name: str) -> bool:
        """
        Check if a file exists in the bucket

        Args:
            object_name: S3 object name (key) in the bucket

        Returns:
            bool: True if file exists, False otherwise
        """
        try:
            self.client.head_object(
                Bucket=self.bucket_name,
                Key=object_name
            )
            return True
        except ClientError:
            return False

    def get_file_url(self, object_name: str) -> str:
        """
        Get the URL for a file in the bucket

        Args:
            object_name: S3 object name (key) in the bucket

        Returns:
            str: Public URL of the file
        """
        return f"{self.endpoint_url}/{self.bucket_name}/{object_name}"

    async def generate_presigned_url(
        self,
        object_name: str,
        expiration: int = 3600
    ) -> str:
        """
        Generate a presigned URL for temporary file access (async)

        Args:
            object_name: S3 object name (key) in the bucket
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            str: Presigned URL

        Raises:
            Exception: If URL generation fails
        """
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                url = await client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': self.bucket_name,
                        'Key': object_name
                    },
                    ExpiresIn=expiration
                )

            # DEBUG, not INFO: this is generated for EVERY document on EVERY
            # document-list fetch (and the sidebar polls every 5s while anything
            # is processing), so at INFO it floods the console. It's cheap local
            # signing, not a network call — just noisy.
            logger.debug(f"Presigned URL generated for: {object_name}")
            return url

        except ClientError as e:
            logger.error(f"❌ Failed to generate presigned URL: {str(e)}")
            raise Exception(f"Failed to generate presigned URL: {str(e)}")

    async def generate_presigned_put_url(
        self,
        object_name: str,
        expiration: int = 3600
    ) -> str:
        """
        Generate a presigned URL the BROWSER can PUT raw file bytes to
        directly, bypassing the backend entirely. No Content-Type is signed
        into the URL, so the caller can send any Content-Type header.

        Args:
            object_name: S3 object name (key) in the bucket
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            str: Presigned PUT URL

        Raises:
            Exception: If URL generation fails
        """
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                url = await client.generate_presigned_url(
                    'put_object',
                    Params={
                        'Bucket': self.bucket_name,
                        'Key': object_name
                    },
                    ExpiresIn=expiration
                )

            logger.info(f"Presigned PUT URL generated for: {object_name}")
            return url

        except ClientError as e:
            logger.error(f"❌ Failed to generate presigned PUT URL: {str(e)}")
            raise Exception(f"Failed to generate presigned PUT URL: {str(e)}")

    # ---------------------------------------------------------------- multipart
    # For large files (videos), a single unresumable PUT is fragile — any
    # network hiccup mid-transfer loses the whole thing with no way to
    # resume. Multipart upload splits the file into parts the BROWSER
    # uploads directly (still bypassing the backend), each with its own
    # presigned URL and its own retry — a failed part only costs that part,
    # not the whole file.

    async def create_multipart_upload(
        self,
        object_name: str,
        content_type: Optional[str] = None
    ) -> str:
        """Start a multipart upload session; returns the upload_id."""
        try:
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type

            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                resp = await client.create_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    **extra_args
                )

            logger.info(f"Multipart upload created for: {object_name}")
            return resp['UploadId']

        except ClientError as e:
            logger.error(f"❌ Failed to create multipart upload for {object_name}: {str(e)}")
            raise Exception(f"Failed to create multipart upload: {str(e)}")

    async def generate_presigned_part_url(
        self,
        object_name: str,
        upload_id: str,
        part_number: int,
        expiration: int = 3600
    ) -> str:
        """Presigned URL for uploading ONE part of a multipart upload."""
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                url = await client.generate_presigned_url(
                    'upload_part',
                    Params={
                        'Bucket': self.bucket_name,
                        'Key': object_name,
                        'UploadId': upload_id,
                        'PartNumber': part_number,
                    },
                    ExpiresIn=expiration
                )
            return url

        except ClientError as e:
            logger.error(f"❌ Failed to generate presigned part URL: {str(e)}")
            raise Exception(f"Failed to generate presigned part URL: {str(e)}")

    async def complete_multipart_upload(
        self,
        object_name: str,
        upload_id: str,
        parts: List[Dict[str, Any]]
    ) -> None:
        """Finalize a multipart upload. `parts` = [{'PartNumber': int, 'ETag': str}, ...]."""
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                await client.complete_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    UploadId=upload_id,
                    MultipartUpload={'Parts': sorted(parts, key=lambda p: p['PartNumber'])}
                )

            logger.info(f"✅ Multipart upload completed: {object_name} ({len(parts)} parts)")

        except ClientError as e:
            logger.error(f"❌ Failed to complete multipart upload for {object_name}: {str(e)}")
            raise Exception(f"Failed to complete multipart upload: {str(e)}")

    async def abort_multipart_upload(self, object_name: str, upload_id: str) -> None:
        """Cancel a multipart upload and release its parts. Best-effort —
        callers use this for cleanup, so a failure here shouldn't crash the
        caller's own error handling."""
        try:
            async with self.session.client(
                's3',
                endpoint_url=self.endpoint_url,
                config=self.config
            ) as client:
                await client.abort_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    UploadId=upload_id
                )
            logger.info(f"🗑️ Multipart upload aborted: {object_name}")

        except ClientError as e:
            logger.warning(f"⚠️ Failed to abort multipart upload for {object_name}: {str(e)}")


# Singleton instance
_idrivee2_client: Optional[IDriveE2Client] = None


def get_idrivee2_client() -> IDriveE2Client:
    """
    Get or create IDriveE2Client singleton instance

    Returns:
        IDriveE2Client: Singleton client instance
    """
    global _idrivee2_client
    if _idrivee2_client is None:
        _idrivee2_client = IDriveE2Client()
    return _idrivee2_client
