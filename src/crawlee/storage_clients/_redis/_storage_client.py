from __future__ import annotations

import warnings

from redis.asyncio import Redis
from typing_extensions import override

from crawlee._utils.docs import docs_group
from crawlee.configuration import Configuration
from crawlee.storage_clients._base import StorageClient

from ._dataset_client import RedisDatasetClient
from ._key_value_store_client import RedisKeyValueStoreClient
from ._request_queue_client import RedisRequestQueueClient


@docs_group('Storage clients')
class RedisStorageClient(StorageClient):
    """Redis implementation of the storage client.

    This storage client provides access to datasets, key-value stores, and request queues that persist data
    to a Redis database v8.0+. Each storage type uses Redis-specific data structures and key patterns for
    efficient storage and retrieval.

    The client accepts either a Redis connection string or a pre-configured Redis client instance.
    Exactly one of these parameters must be provided during initialization.

    Storage types use the following Redis data structures:
    - **Datasets**: Redis JSON arrays for item storage with metadata in JSON objects
    - **Key-Value Stores**: Redis hashes for key-value pairs with separate metadata storage
    - **Request Queues**: Redis lists for FIFO queuing, hashes for request data and in-progress tracking,
      and Bloom filters for request deduplication

    Warning:
        This is an experimental feature. The behavior and interface may change in future versions.
    """

    def __init__(
        self,
        *,
        connection_string: str | None = None,
        redis: Redis | None = None,
    ) -> None:
        """Initialize the Redis storage client.

        Args:
            connection_string: Redis connection string (e.g., "redis://localhost:6379").
                Supports standard Redis URL format with optional database selection.
            redis: Pre-configured Redis client instance.
        """
        if redis is not None and connection_string is not None:
            raise ValueError('Either redis or connection_string must be provided, not both.')

        if redis is None and connection_string is None:
            raise ValueError('Either redis or connection_string must be provided.')

        if redis is not None:
            self._redis = redis

        elif connection_string is not None:
            self._redis = Redis.from_url(connection_string)

        # Call the notification only once
        warnings.warn(
            'The RedisStorageClient is experimental and may change or be removed in future releases.',
            category=UserWarning,
            stacklevel=2,
        )

    @override
    async def create_dataset_client(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        alias: str | None = None,
        configuration: Configuration | None = None,
    ) -> RedisDatasetClient:
        configuration = configuration or Configuration.get_global_configuration()

        client = await RedisDatasetClient.open(
            id=id,
            name=name,
            alias=alias,
            redis=self._redis,
        )

        await self._purge_if_needed(client, configuration)
        return client

    @override
    async def create_kvs_client(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        alias: str | None = None,
        configuration: Configuration | None = None,
    ) -> RedisKeyValueStoreClient:
        configuration = configuration or Configuration.get_global_configuration()

        client = await RedisKeyValueStoreClient.open(
            id=id,
            name=name,
            alias=alias,
            redis=self._redis,
        )

        await self._purge_if_needed(client, configuration)
        return client

    @override
    async def create_rq_client(
        self,
        *,
        id: str | None = None,
        name: str | None = None,
        alias: str | None = None,
        configuration: Configuration | None = None,
    ) -> RedisRequestQueueClient:
        configuration = configuration or Configuration.get_global_configuration()

        client = await RedisRequestQueueClient.open(
            id=id,
            name=name,
            alias=alias,
            redis=self._redis,
        )

        await self._purge_if_needed(client, configuration)
        return client
