"""MLB.TV API session — handles Okta auth and stream URL retrieval."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

# Okta / MLB constants (from the Kodi plugin.video.mlbtv)
OKTA_TOKEN_URL = "https://ids.mlb.com/oauth2/aus1m088yK07noBfh356/v1/token"
OKTA_CLIENT_ID = "0oa3e1nutA1HLzAKG356"
GRAPHQL_URL = "https://media-gateway.mlb.com/graphql"

_INIT_SESSION_MUTATION = (
    "mutation initSession($device: InitSessionInput!, $clientType: ClientType!, "
    "$experience: ExperienceTypeInput) { initSession(device: $device, clientType: "
    "$clientType, experience: $experience) { deviceId sessionId entitlements { code } "
    "location { countryCode regionName zipCode latitude longitude } "
    "clientExperience features } }"
)

_CONTENT_SEARCH_QUERY = (
    "query contentSearch($query: String!, $limit: Int = 10, $skip: Int = 0) { "
    "contentSearch(query: $query, limit: $limit, skip: $skip) { total content { "
    "contentId mediaId contentType feedType callSign mediaState { state mediaType "
    "contentExperience } } } }"
)

_PLAYBACK_SESSION_MUTATION = (
    "mutation initPlaybackSession($adCapabilities: [AdExperienceType], "
    "$mediaId: String!, $deviceId: String!, $sessionId: String!, "
    "$quality: PlaybackQuality) { initPlaybackSession(adCapabilities: "
    "$adCapabilities, mediaId: $mediaId, deviceId: $deviceId, sessionId: "
    "$sessionId, quality: $quality) { playbackSessionId playback { url token "
    "expiration cdn } heartbeatInfo { url interval } } }"
)

_WEB_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class MLBSession:
    """Handles MLB.TV authentication and stream access via API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._device_id: str | None = None
        self._session_id: str | None = None
        self._username: str | None = None
        self._password: str | None = None

    # ── Public API ──────────────────────────────────────────────

    async def login(self, username: str, password: str) -> bool:
        """Authenticate with MLB.TV via Okta password grant."""
        self._username = username
        self._password = password

        try:
            resp = await self._client.post(
                OKTA_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "username": username,
                    "password": password,
                    "scope": "openid offline_access",
                    "client_id": OKTA_CLIENT_ID,
                },
                headers={"User-Agent": "okhttp/3.12.1"},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            log.error("Okta login failed (HTTP %d): %s", e.response.status_code, e.response.text[:200])
            return False
        except Exception:
            log.exception("Okta login request failed")
            return False

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        log.info("Okta login successful (token expires in %ds)", expires_in)

        # Initialize GraphQL session
        try:
            await self._init_session()
            return True
        except Exception:
            log.exception("Failed to initialize MLB session after login")
            return False

    @property
    def is_authenticated(self) -> bool:
        return (
            self._access_token is not None
            and self._token_expiry is not None
            and datetime.now(timezone.utc) < self._token_expiry
        )

    async def ensure_authenticated(self) -> bool:
        """Re-login if the token has expired. Returns True if authenticated."""
        if self.is_authenticated:
            return True
        if self._username and self._password:
            log.info("Token expired — re-authenticating...")
            return await self.login(self._username, self._password)
        return False

    async def get_stream_url(self, game_id: str, feed_type: str = "HOME") -> str | None:
        """Get an HLS stream URL for a game. Returns None on failure."""
        if not await self.ensure_authenticated():
            log.error("Cannot get stream — not authenticated")
            return None

        # Step 1: Find the mediaId for this game
        media_id = await self._get_media_id(game_id, feed_type)
        if not media_id:
            log.error("No media found for game %s (feed=%s)", game_id, feed_type)
            return None

        # Step 2: Get the playback stream URL
        try:
            result = await self._graphql("initPlaybackSession", _PLAYBACK_SESSION_MUTATION, {
                "adCapabilities": ["GOOGLE_STANDALONE_AD_PODS"],
                "mediaId": media_id,
                "deviceId": self._device_id,
                "sessionId": self._session_id,
                "quality": "PLACEHOLDER",
            })
            url = result["data"]["initPlaybackSession"]["playback"]["url"]
            log.info("Got stream URL for game %s (feed=%s)", game_id, feed_type)
            return url
        except Exception:
            log.exception("Failed to get playback session for game %s", game_id)
            return None

    async def close(self) -> None:
        await self._client.aclose()

    # ── Internals ───────────────────────────────────────────────

    async def _init_session(self) -> None:
        """Initialize a GraphQL media session."""
        result = await self._graphql("initSession", _INIT_SESSION_MUTATION, {
            "device": {
                "appVersion": "7.8.2",
                "deviceFamily": "desktop",
                "knownDeviceId": "",
                "languagePreference": "ENGLISH",
                "manufacturer": "Google Inc.",
                "model": "",
                "os": "linux",
                "osVersion": "1.0",
            },
            "clientType": "WEB",
        })
        session = result["data"]["initSession"]
        self._device_id = session["deviceId"]
        self._session_id = session["sessionId"]
        entitlements = [e["code"] for e in session.get("entitlements", [])]
        log.info(
            "MLB session initialized (device=%s, entitlements=%s)",
            self._device_id[:12] + "...",
            entitlements,
        )

    async def _get_media_id(self, game_id: str, feed_type: str) -> str | None:
        """Look up the mediaId for a game via content search."""
        try:
            result = await self._graphql("contentSearch", _CONTENT_SEARCH_QUERY, {
                "query": (
                    f'GamePk={game_id} AND ContentType="GAME"'
                    " RETURNING HomeTeamId, HomeTeamName, AwayTeamId,"
                    " AwayTeamName, Date, MediaType, ContentExperience,"
                    " MediaState, PartnerCallLetters"
                ),
                "limit": 16,
            })
        except Exception:
            log.exception("Content search failed for game %s", game_id)
            return None

        contents = result.get("data", {}).get("contentSearch", {}).get("content", [])
        if not contents:
            return None

        # Prefer the requested feed type, fall back to any available
        for item in contents:
            if item.get("feedType", "").upper() == feed_type.upper():
                return item["mediaId"]

        # No matching feed — return the first one
        return contents[0].get("mediaId")

    async def _graphql(self, operation: str, query: str, variables: dict) -> dict:
        """Execute a GraphQL request against the MLB media gateway."""
        resp = await self._client.post(
            GRAPHQL_URL,
            json={
                "operationName": operation,
                "query": query,
                "variables": variables,
            },
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "User-Agent": _WEB_USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            log.error("GraphQL errors for %s: %s", operation, data["errors"])
            raise RuntimeError(f"GraphQL error in {operation}: {data['errors']}")
        return data
