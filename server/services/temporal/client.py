"""Temporal client wrapper for MachinaOs.

Manages the Temporal client connection lifecycle with retry support.
"""

import asyncio
from typing import Optional
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.runtime import LoggingConfig, Runtime, TelemetryConfig

from core.logging import get_logger

logger = get_logger(__name__)


class TemporalClientWrapper:
    """Wrapper around Temporal client for lifecycle management."""

    def __init__(self, server_address: str, namespace: str = "default"):
        self.server_address = server_address
        self.namespace = namespace
        self._client: Optional[Client] = None
        self._runtime: Optional[Runtime] = None

    @property
    def client(self) -> Optional[Client]:
        """Get the underlying Temporal client."""
        return self._client

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._client is not None

    async def connect(self, retries: int = 3, delay: float = 2.0) -> Optional[Client]:
        """Connect to the Temporal server with retries.

        Returns:
            The connected Temporal client, or None if connection failed.
        """
        if self._client is not None:
            return self._client

        # Create runtime once (reusable across reconnects)
        if self._runtime is None:
            self._runtime = Runtime(
                telemetry=TelemetryConfig(
                    logging=LoggingConfig(filter="ERROR"),
                ),
                worker_heartbeat_interval=None,
            )

        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    f"Connecting to Temporal server (attempt {attempt}/{retries})",
                    server_address=self.server_address,
                    namespace=self.namespace,
                )
                client = await Client.connect(
                    self.server_address,
                    namespace=self.namespace,
                    runtime=self._runtime,
                )
                # Verify namespace is ready (gRPC port may accept connections
                # before the server finishes registering namespaces)
                await client.service_client.workflow_service.describe_namespace(
                    DescribeNamespaceRequest(namespace=self.namespace)
                )
                self._client = client
                logger.info(f"Connected to Temporal server at {self.server_address}")
                # Wave 12 A4: idempotently register the event-framework
                # Search Attributes. Failure here is non-fatal — the
                # framework still works without them, dispatch.emit just
                # falls back to broadcast-only routing instead of
                # signalling consumers.
                try:
                    from services.temporal.search_attributes import (
                        register_search_attributes,
                    )
                    await register_search_attributes(self._client, self.namespace)
                except Exception as sa_exc:  # noqa: BLE001 — non-fatal
                    logger.warning(
                        f"Search-attribute registration failed (non-fatal): {sa_exc}"
                    )
                return self._client
            except Exception as e:
                logger.warning(
                    f"Temporal connection attempt {attempt}/{retries} failed: {e}"
                )
                if attempt < retries:
                    await asyncio.sleep(delay)

        logger.error(
            f"Failed to connect to Temporal server at {self.server_address} after {retries} attempts"
        )
        return None

    async def disconnect(self) -> None:
        """Disconnect from the Temporal server."""
        if self._client is not None:
            self._client = None
            logger.info("Disconnected from Temporal server")
