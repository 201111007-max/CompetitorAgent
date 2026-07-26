"""Unified async OpenDota API client.

Merges the sync request pattern from utils/api_client.py with the async
httpx-based client from dota_helper/data_source/opendota_client.py.

Features:
- httpx.AsyncClient with lazy init + event-loop change detection
- Exponential backoff retry (1s, 2s, 4s) + 429 special handling (wait 60s+)
- Instance-level caching (heroes list, items map, constants)
- Singleton pattern: get_instance() / set_instance()
- Generic async get() / post() methods
- API key support via OPENDOTA_API_KEY env var
- Python 3.9 compatible (Optional[X] instead of X | None)
- async context manager support (__aenter__ / __aexit__)
- Configurable rate-limit delay between requests (default 1.0s)
- Module-level stdlib logger
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class OpenDotaAPIError(Exception):
    """Raised when an OpenDota API call fails after exhausting retries."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenDotaClient:
    """Unified async OpenDota HTTP client.

    Usage::

        async with OpenDotaClient() as client:
            match = await client.get("/matches/12345")
            heroes = await client.get_heroes()

    Or with the singleton::

        OpenDotaClient.set_instance(OpenDotaClient())
        client = OpenDotaClient.get_instance()
    """

    BASE_URL: str = "https://api.opendota.com/api"

    # -- class-level singleton ------------------------------------------------

    _instance: Optional["OpenDotaClient"] = None

    @classmethod
    def get_instance(cls) -> Optional["OpenDotaClient"]:
        """Return the globally registered singleton, or *None*."""
        return cls._instance

    @classmethod
    def set_instance(cls, client: Optional["OpenDotaClient"]) -> None:
        """Register (or clear with *None*) the global singleton."""
        cls._instance = client

    # -- constructor ----------------------------------------------------------

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limit_delay: float = 1.0,
        api_key: Optional[str] = None,
    ) -> None:
        """Initialise the client.

        Args:
            base_url: OpenDota API base URL.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            rate_limit_delay: Minimum seconds between consecutive requests.
            api_key: OpenDota API key. Falls back to the
                ``OPENDOTA_API_KEY`` environment variable.
        """
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._rate_limit_delay = rate_limit_delay
        self._api_key: Optional[str] = api_key or os.getenv("OPENDOTA_API_KEY")

        # Lazy-initialised httpx client (created on first use)
        self._client: Optional[httpx.AsyncClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Rate-limit bookkeeping
        self._last_request_time: float = 0.0

        # Instance-level caches
        self._heroes_cache: Optional[List[Dict[str, Any]]] = None
        self._items_cache: Optional[Dict[int, Dict[str, Any]]] = None
        self._constants_cache: Optional[Dict[str, Any]] = None
        self._hero_map_cache: Optional[Dict[int, str]] = None
        self._items_map_cache: Optional[Dict[int, Dict[str, Any]]] = None
        self._constants_resource_cache: Optional[Dict[str, Any]] = None
        self._item_id_map_cache: Optional[Dict[str, Dict[str, str]]] = None

    # -- lazy httpx client ----------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (or create) the underlying ``httpx.AsyncClient``.

        If the running event loop has changed since the client was created
        (e.g. Flask running each request in a separate loop), the old client
        is closed and a new one is instantiated.  This prevents
        ``Event loop is closed`` errors.
        """
        loop = asyncio.get_running_loop()
        if (
            self._client is None
            or self._client.is_closed
            or self._loop is not loop
        ):
            if self._client is not None and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Closing old httpx client, ignoring: %s", exc)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
            self._loop = loop
        return self._client

    # -- rate limiter ---------------------------------------------------------

    async def _enforce_rate_limit(self) -> None:
        """Sleep if necessary to honour ``_rate_limit_delay``."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            wait = self._rate_limit_delay - elapsed
            logger.debug("Rate-limit: sleeping %.2fs", wait)
            await asyncio.sleep(wait)

    # -- generic request methods ----------------------------------------------

    def _build_params(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge caller params with the API key (if configured)."""
        merged: Dict[str, Any] = dict(params) if params else {}
        if self._api_key:
            merged["api_key"] = self._api_key
        return merged

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Issue an async GET request with retry and back-off.

        Args:
            endpoint: API path relative to *base_url* (e.g. ``/matches/123``).
            params: Optional query parameters.

        Returns:
            Parsed JSON response (dict / list / primitive).

        Raises:
            OpenDotaAPIError: After all retries are exhausted.
        """
        return await self._request("GET", endpoint, params=params)

    async def post(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Issue an async POST request with retry and back-off.

        Args:
            endpoint: API path relative to *base_url*.
            params: Optional query parameters.
            json_body: Optional JSON body.

        Returns:
            Parsed JSON response.

        Raises:
            OpenDotaAPIError: After all retries are exhausted.
        """
        return await self._request(
            "POST", endpoint, params=params, json_body=json_body
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Core request loop with exponential back-off and 429 handling.

        Back-off sequence: 1s, 2s, 4s (powers of two).
        On HTTP 429 the wait is ``60 + attempt * 10`` seconds.
        """
        request_params = self._build_params(params)
        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            await self._enforce_rate_limit()

            try:
                client = await self._get_client()
                if method.upper() == "POST":
                    response = await client.post(
                        endpoint,
                        params=request_params,
                        json=json_body,
                    )
                else:
                    response = await client.get(
                        endpoint,
                        params=request_params,
                    )

                self._last_request_time = time.monotonic()

                status_code = response.status_code

                # -- 429: rate-limited by upstream ----------------------
                if status_code == 429:
                    wait_time = 60 + attempt * 10
                    logger.warning(
                        "HTTP 429 rate-limited on %s (attempt %d/%d), "
                        "waiting %ds",
                        endpoint,
                        attempt,
                        self._max_retries,
                        wait_time,
                    )
                    if attempt >= self._max_retries:
                        raise OpenDotaAPIError(
                            f"HTTP 429 after {self._max_retries} retries on {endpoint}",
                            status_code=429,
                        )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()
                logger.info(
                    "GET %s succeeded (attempt %d, status %d)",
                    endpoint,
                    attempt,
                    status_code,
                )
                return data

            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                # 4xx (except 429 handled above) -> no retry
                if 400 <= status_code < 500:
                    raise OpenDotaAPIError(
                        f"API error on {endpoint}: HTTP {status_code}",
                        status_code=status_code,
                    ) from exc
                logger.warning(
                    "HTTP %d on %s (attempt %d/%d)",
                    status_code,
                    endpoint,
                    attempt,
                    self._max_retries,
                )

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s",
                    endpoint,
                    attempt,
                    self._max_retries,
                    exc,
                )

            # -- exponential back-off before next attempt ---------------
            if attempt < self._max_retries:
                backoff = 2 ** (attempt - 1)  # 1, 2, 4, ...
                logger.debug("Back-off: sleeping %ds before retry", backoff)
                await asyncio.sleep(backoff)

        raise OpenDotaAPIError(
            f"Request to {endpoint} failed after {self._max_retries} retries: "
            f"{last_error}",
        ) from last_error

    # -- convenience methods (instance-cached) --------------------------------

    async def get_heroes(
        self,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch the hero roster.

        Results are cached at the instance level so subsequent calls are
        free (within the same client lifetime).
        """
        if use_cache and self._heroes_cache is not None:
            return self._heroes_cache
        data = await self.get("/heroes")
        heroes: List[Dict[str, Any]] = data if isinstance(data, list) else []
        self._heroes_cache = heroes
        return heroes

    async def get_hero_stats(
        self,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch hero statistics (win-rate, pick-rate, etc.)."""
        if use_cache and self._heroes_cache is not None:
            # heroStats is richer; we still keep it under the same slot
            # but only if the caller is okay with a previous fetch.
            pass  # fall through — heroStats != heroes list
        data = await self.get("/heroStats")
        result: List[Dict[str, Any]] = data if isinstance(data, list) else []
        return result

    async def get_hero_matchups(
        self,
        hero_id: int,
    ) -> List[Dict[str, Any]]:
        """Fetch matchup data for a single hero."""
        data = await self.get(f"/heroes/{hero_id}/matchups")
        return data if isinstance(data, list) else []

    async def get_hero_item_popularity(
        self,
        hero_id: int,
    ) -> Dict[str, Any]:
        """Fetch item popularity data for a single hero."""
        data = await self.get(f"/heroes/{hero_id}/itemPopularity")
        return data if isinstance(data, dict) else {}

    async def get_match_details(
        self,
        match_id: str,
    ) -> Dict[str, Any]:
        """Fetch full match details by match ID."""
        data = await self.get(f"/matches/{match_id}")
        return data if isinstance(data, dict) else {}

    async def get_player_matches(
        self,
        account_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent matches for a player.

        Args:
            account_id: Steam32 account ID.
            limit: Optional limit on the number of matches returned.
        """
        params: Optional[Dict[str, Any]] = None
        if limit is not None:
            params = {"limit": str(limit)}
        data = await self.get(f"/players/{account_id}/matches", params=params)
        return data if isinstance(data, list) else []

    async def get_player_recent_matches(
        self,
        account_id: str,
    ) -> List[Dict[str, Any]]:
        """Fetch the player's most recent matches (shorthand)."""
        data = await self.get(f"/players/{account_id}/recentMatches")
        return data if isinstance(data, list) else []

    async def get_items(
        self,
        use_cache: bool = True,
    ) -> Dict[int, Dict[str, Any]]:
        """Fetch item constants and cache as ``{item_id: item_dict}``."""
        if use_cache and self._items_cache is not None:
            return self._items_cache
        constants = await self.get_constants(use_cache=use_cache)
        raw_items = constants.get("items", [])
        items_map: Dict[int, Dict[str, Any]] = {}
        if isinstance(raw_items, list):
            for item in raw_items:
                item_id = item.get("id")
                if item_id is not None:
                    items_map[item_id] = item
        self._items_cache = items_map
        return items_map

    async def get_constants(
        self,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Fetch game constants (heroes, items, abilities, …).

        Results are cached at the instance level.
        """
        if use_cache and self._constants_cache is not None:
            return self._constants_cache
        data = await self.get("/constants")
        constants: Dict[str, Any] = data if isinstance(data, dict) else {}
        self._constants_cache = constants
        return constants

    async def get_pro_matches(self) -> List[Dict[str, Any]]:
        """Fetch recent professional matches."""
        data = await self.get("/proMatches")
        return data if isinstance(data, list) else []

    async def get_public_matches(
        self,
        mmr_ascending: Optional[int] = None,
        mmr_descending: Optional[int] = None,
        less_than_match_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent public matches with optional MMR filtering."""
        params: Dict[str, Any] = {}
        if mmr_ascending is not None:
            params["mmr_ascending"] = str(mmr_ascending)
        if mmr_descending is not None:
            params["mmr_descending"] = str(mmr_descending)
        if less_than_match_id is not None:
            params["less_than_match_id"] = str(less_than_match_id)
        data = await self.get("/publicMatches", params=params or None)
        return data if isinstance(data, list) else []

    # -- hero name/id helpers -------------------------------------------------

    async def hero_name_to_id(self, hero_name: str) -> Optional[int]:
        """Convert a hero name (localized or internal) to its numeric ID.

        Matching is case-insensitive and tries several formats:
        ``localized_name``, internal ``name``, the stripped internal name
        (without ``npc_dota_hero_``), and underscore / hyphen variants.
        """
        heroes = await self.get_heroes()
        query = hero_name.lower().strip()

        for hero in heroes:
            # localized_name (e.g. "Faceless Void")
            if hero.get("localized_name", "").lower() == query:
                return hero["id"]

            # internal name (e.g. "npc_dota_hero_faceless_void")
            internal = hero.get("name", "").lower()
            if internal == query:
                return hero["id"]

            # stripped internal name (e.g. "faceless_void")
            stripped = internal.replace("npc_dota_hero_", "")
            if stripped == query:
                return hero["id"]

            # localized name with spaces -> underscores
            if hero.get("localized_name", "").lower().replace(" ", "_") == query:
                return hero["id"]

            # fuzzy: strip hyphens/underscores and compare
            if (
                query.replace("-", "").replace("_", "")
                == stripped.replace("-", "").replace("_", "")
            ):
                return hero["id"]

        return None

    async def hero_id_to_name(self, hero_id: int) -> str:
        """Convert a hero ID to its localized display name."""
        heroes = await self.get_heroes()
        for hero in heroes:
            if hero.get("id") == hero_id:
                return hero.get("localized_name", "Unknown")
        return "Unknown"

    # -- lifecycle ------------------------------------------------------------

    # -- tool-facing convenience methods ----------------------------------------

    async def get_cached_hero_map(self) -> Dict[int, str]:
        """Return a hero-id -> localized-name mapping, cached at instance level.

        Returns:
            Dict[int, str]: Mapping of hero ID to English localized name.
        """
        if self._hero_map_cache is not None:
            return self._hero_map_cache
        heroes = await self.get_heroes()
        hero_map: Dict[int, str] = {
            h["id"]: h.get("localized_name", f"Hero {h['id']}")
            for h in heroes
            if isinstance(h, dict) and "id" in h
        }
        self._hero_map_cache = hero_map
        return hero_map

    async def get_cached_items_map(self) -> Dict[int, Dict[str, Any]]:
        """Return an item-id -> {key, name, qual} mapping, cached at instance level.

        The mapping is built from the ``/constants/items`` endpoint.  Each
        entry contains ``key`` (internal item key), ``name`` (display name),
        and ``qual`` (quality / category).

        Returns:
            Dict[int, Dict[str, Any]]: Item ID to item info mapping.
        """
        if self._items_map_cache is not None:
            return self._items_map_cache
        constants = await self.get_constants()
        raw_items = constants.get("items", {})
        items_map: Dict[int, Dict[str, Any]] = {}
        if isinstance(raw_items, dict):
            for key, info in raw_items.items():
                if not isinstance(info, dict):
                    continue
                item_id = info.get("id")
                if item_id is None:
                    continue
                try:
                    item_id_int = int(item_id)
                except (TypeError, ValueError):
                    continue
                name = info.get("dname") or info.get("name") or key
                items_map[item_id_int] = {
                    "key": str(key),
                    "name": str(name),
                    "qual": info.get("qual"),
                }
        self._items_map_cache = items_map
        return items_map

    def build_item_entry(
        self,
        item_id: Any,
        items_map: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a single item info dict from an item ID.

        This is a synchronous helper that performs a dict lookup against the
        provided *items_map* (or the instance cache when *None*).

        Args:
            item_id: Numeric item ID (may be str or int).
            items_map: Optional item mapping.  When *None*, the instance-level
                cache (``_items_map_cache``) is used.

        Returns:
            A dict with ``id``, ``key``, ``name`` keys, or *None* when the
            item ID is invalid / empty.
        """
        if item_id is None:
            return None
        try:
            item_id_int = int(item_id)
        except (TypeError, ValueError):
            return None
        if item_id_int <= 0:
            return None
        lookup = items_map if items_map is not None else self._items_map_cache
        if lookup is not None:
            info = lookup.get(item_id_int)
            if info:
                return {"id": item_id_int, "key": info.get("key"), "name": info.get("name")}
        return {"id": item_id_int, "key": None, "name": None}

    async def get_cached_constants(self, resource: str) -> Any:
        """Fetch a single constants resource, cached at instance level.

        The first call for a given *resource* hits the API; subsequent calls
        return the cached value.

        Args:
            resource: Constants resource name (e.g. ``"heroes"``, ``"items"``,
                ``"abilities"``).

        Returns:
            The parsed JSON data (typically dict or list).
        """
        if self._constants_resource_cache is None:
            self._constants_resource_cache: Dict[str, Any] = {}
        if resource in self._constants_resource_cache:
            return self._constants_resource_cache[resource]
        data = await self.get(f"/constants/{resource}")
        self._constants_resource_cache[resource] = data
        return data

    async def get_cached_item_id_map(self) -> Dict[str, Dict[str, str]]:
        """Load the by-id item mapping from the constants items data.

        Returns:
            Dict[str, Dict[str, str]]: Mapping of ``str(item_id)`` to item
                info (``key``, ``name``, etc.).
        """
        if self._item_id_map_cache is not None:
            return self._item_id_map_cache
        items_map = await self.get_cached_items_map()
        by_id: Dict[str, Dict[str, str]] = {}
        for item_id_int, info in items_map.items():
            by_id[str(item_id_int)] = {
                "id": str(item_id_int),
                "key": info.get("key", ""),
                "name": info.get("name", ""),
            }
        self._item_id_map_cache = by_id
        return by_id

    # -- lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` (idempotent)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> "OpenDotaClient":
        """Async context-manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Async context-manager exit — ensures ``close()`` is called."""
        await self.close()


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

AsyncOpenDotaClient = OpenDotaClient
"""Alias so that existing ``from ... import AsyncOpenDotaClient`` continues to work."""
