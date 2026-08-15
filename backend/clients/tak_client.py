"""
TAK Client - Connects to TAK Server and sends CoT messages using pytak

Wrapper around official pytak library for sending CoT messages to TAK servers.
Supports both plain TCP and TLS/SSL connections with optional authentication.
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Optional
from configparser import ConfigParser
from datetime import datetime, timezone, timedelta
import time

import pytak

logger = logging.getLogger(__name__)


class TAKClient:
    """
    TAK client for sending CoT (Cursor on Target) messages using pytak.

    Supports:
    - Plain TCP connections (port 8087)
    - TLS/SSL connections (port 8089)
    - Optional username/password authentication
    - Both public and private TAK servers

    Usage:
        # Public server (no auth, TCP)
        client = TAKClient(host="137.184.101.250", port=8087)
        await client.connect()
        await client.send_cot(cot_xml_string)
        await client.disconnect()

        # Private server (with auth, SSL)
        client = TAKClient(
            host="tak.company.com",
            port=8089,
            username="soldieriq-agent",
            password="mypassword",
            use_tls=True
        )

        # Or use as async context manager
        async with TAKClient(...) as client:
            await client.send_cot(cot_xml)
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = False,
        timeout: int = 10
    ):
        """
        Initialize TAK client.

        Args:
            host: TAK server hostname or IP
            port: TAK server port (8087 for TCP, 8089 for SSL)
            username: Username for authentication (optional)
            password: Password for authentication (optional)
            use_tls: Use TLS/SSL connection (default: False for port 8087, True for 8089)
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout

        # Auto-detect TLS based on port if not explicitly set
        if use_tls or port == 8089:
            self.protocol = "tls"
        else:
            self.protocol = "tcp"

        self.cot_url = f"{self.protocol}://{host}:{port}"

        # pytak components
        self.clitool: Optional[pytak.CLITool] = None
        self._connected = False
        self._worker_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """
        Connect to TAK server.

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            logger.info(f"Connecting to TAK server at {self.cot_url}")

            # Create config for pytak
            config = ConfigParser()
            config["pytak"] = {
                "COT_URL": self.cot_url,
                "FTS_COMPAT": "False",  # Disable FTS compatibility delays
            }

            # Add TLS settings if using SSL (for production servers)
            if self.protocol == "tls":
                # For now, we'll use pytak's default TLS settings
                # In production, you'd add cert/key paths here
                pass

            # Initialize pytak CLITool
            self.clitool = pytak.CLITool(config["pytak"])
            await self.clitool.setup()

            # Start the TX worker in the background to actually send messages
            self._worker_task = asyncio.create_task(self._run_worker())

            # If username/password provided, send auth CoT message
            if self.username and self.password:
                logger.info(f"Authenticating as user: {self.username}")
                auth_success = await self._send_auth()

                if not auth_success:
                    logger.error("Authentication failed")
                    return False

                logger.info("Authentication successful")

            self._connected = True
            logger.info("Successfully connected to TAK server")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to TAK server: {e}")
            self._connected = False
            return False

    async def _run_worker(self):
        """Run the pytak worker to process the TX queue."""
        try:
            await self.clitool.run()
        except asyncio.CancelledError:
            logger.debug("Worker task cancelled")
        except Exception as e:
            logger.error(f"Worker task error: {e}")

    async def _send_auth(self) -> bool:
        """
        Send authentication CoT message to TAK server.

        Returns:
            True if auth message sent successfully
        """
        try:
            # Build auth CoT message
            now = datetime.now(timezone.utc)
            stale = now + timedelta(minutes=1)

            # Auth CoT message format
            root = ET.Element("event")
            root.set("version", "2.0")
            root.set("uid", f"auth-{int(time.time())}")
            root.set("type", "t-x-c-t")
            root.set("time", now.isoformat())
            root.set("start", now.isoformat())
            root.set("stale", stale.isoformat())
            root.set("how", "h-e")

            # Point element (required)
            point = ET.SubElement(root, "point")
            point.set("lat", "0")
            point.set("lon", "0")
            point.set("hae", "0")
            point.set("ce", "9999999")
            point.set("le", "9999999")

            # Detail with auth
            detail = ET.SubElement(root, "detail")
            auth = ET.SubElement(detail, "auth")
            auth.set("username", self.username)
            auth.set("password", self.password)

            auth_cot = ET.tostring(root, encoding="unicode")

            # Send auth message through pytak queue
            await self.clitool.tx_queue.put(auth_cot.encode('utf-8'))

            # Give server a moment to process auth
            await asyncio.sleep(0.5)

            logger.debug("Sent authentication CoT message")
            return True

        except Exception as e:
            logger.error(f"Failed to send auth message: {e}")
            return False

    async def send_cot(self, cot_xml: str) -> bool:
        """
        Send a CoT XML message to TAK server.

        Args:
            cot_xml: CoT message in XML format (string or bytes)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._connected or not self.clitool:
            logger.error("Not connected to TAK server. Call connect() first.")
            return False

        try:
            # Ensure we have bytes
            if isinstance(cot_xml, str):
                message_bytes = cot_xml.encode('utf-8')
            else:
                message_bytes = cot_xml

            # Put message in TX queue - pytak workers will send it
            await self.clitool.tx_queue.put(message_bytes)

            logger.debug(f"Queued CoT message ({len(message_bytes)} bytes)")

            # Small delay to ensure message is sent
            await asyncio.sleep(0.1)

            return True

        except Exception as e:
            logger.error(f"Failed to send CoT message: {e}")
            return False

    async def disconnect(self):
        """Close connection to TAK server."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self.clitool:
            try:
                logger.info("Disconnected from TAK server")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
            finally:
                self.clitool = None
                self._connected = False

    def is_connected(self) -> bool:
        """Check if currently connected to TAK server."""
        return self._connected and self.clitool is not None

    async def __aenter__(self):
        """Async context manager support."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager cleanup."""
        await self.disconnect()


# Synchronous wrapper for non-async contexts
def send_cot_sync(
    host: str,
    port: int,
    cot_xml: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: bool = False
) -> bool:
    """
    Synchronous wrapper to send a single CoT message.

    This is a convenience function for sending one-off CoT messages
    without managing async contexts.

    Args:
        host: TAK server hostname or IP
        port: TAK server port
        cot_xml: CoT message XML string
        username: Optional username for authentication
        password: Optional password for authentication
        use_tls: Use TLS/SSL connection

    Returns:
        True if sent successfully, False otherwise
    """
    async def _send():
        async with TAKClient(host, port, username, password, use_tls) as client:
            return await client.send_cot(cot_xml)

    try:
        return asyncio.run(_send())
    except Exception as e:
        logger.error(f"Failed to send CoT message: {e}")
        return False


# Legacy singleton support (for backward compatibility)
_tak_client_instance: Optional[TAKClient] = None


def get_tak_client(
    host: str = None,
    port: int = None,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> TAKClient:
    """
    Get or create singleton TAK client instance.

    Note: This is for backward compatibility. Prefer using TAKClient directly.

    Args:
        host: TAK server host (only used on first call)
        port: TAK server port (only used on first call)
        username: Username for authentication
        password: Password for authentication

    Returns:
        TAKClient instance
    """
    global _tak_client_instance

    if _tak_client_instance is None:
        if host is None or port is None:
            raise ValueError("host and port required for first call to get_tak_client")
        _tak_client_instance = TAKClient(
            host=host,
            port=port,
            username=username,
            password=password
        )

    return _tak_client_instance
