import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx


class OpenF1Client:
    """Client for OpenF1 REST API with automatic local JSON caching."""

    BASE_URL = "https://api.openf1.org/v1"

    def __init__(self, cache_dir: str = "data/cache/openf1"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": "PitWatchAI/0.1.0"}

    def _get_cache_path(self, endpoint: str, params: Dict[str, Any]) -> Path:
        sanitized_params = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
        filename = f"{endpoint}_{sanitized_params}.json" if sanitized_params else f"{endpoint}.json"
        return self.cache_dir / filename

    async def _fetch_cached(self, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        cache_path = self._get_cache_path(endpoint, params)
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)

        url = f"{self.BASE_URL}/{endpoint}"
        async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        return data

    async def get_sessions(self, year: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("sessions", {"year": year})

    async def get_drivers(self, session_key: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("drivers", {"session_key": session_key})

    async def get_weather(self, session_key: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("weather", {"session_key": session_key})

    async def get_location(self, session_key: int, driver_number: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_cached("location", params)

    async def get_car_data(self, session_key: int, driver_number: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_cached("car_data", params)

    async def get_team_radio(self, session_key: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("team_radio", {"session_key": session_key})

    async def get_laps(self, session_key: int, driver_number: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_cached("laps", params)
