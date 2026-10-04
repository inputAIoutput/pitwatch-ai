import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx


import os

class OpenF1Client:
    """Client for OpenF1 REST API with automatic local JSON caching."""

    BASE_URL = "https://api.openf1.org/v1"

    def __init__(self, cache_dir: str = "data/cache/openf1", api_token: Optional[str] = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": "PitWatchAI/0.1.0"}
        token = api_token or os.environ.get("OPENF1_TOKEN") or os.environ.get("OPENF1_API_KEY")
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

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

    async def _fetch_live(self, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/{endpoint}"
        async with httpx.AsyncClient(headers=self.headers, timeout=10.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 401:
                detail = response.json().get("detail", "Unauthorized") if response.headers.get("content-type", "").startswith("application/json") else response.text
                print(f"[PitWatch AI] [WARN] OpenF1 Live Auth Required (401): {detail}")
                return []
            response.raise_for_status()
            return response.json()

    async def get_sessions(self, year: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("sessions", {"year": year})

    async def get_drivers(self, session_key: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("drivers", {"session_key": session_key})

    async def get_weather(
        self,
        session_key: int,
        bypass_cache: bool = False,
        date_gt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if date_gt:
            params["date>"] = date_gt
        if bypass_cache:
            return await self._fetch_live("weather", params)
        return await self._fetch_cached("weather", params)

    async def get_location(
        self,
        session_key: int,
        driver_number: Optional[int] = None,
        bypass_cache: bool = False,
        date_gt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        if date_gt:
            params["date>"] = date_gt
        if bypass_cache:
            return await self._fetch_live("location", params)
        return await self._fetch_cached("location", params)

    async def get_car_data(
        self,
        session_key: int,
        driver_number: Optional[int] = None,
        bypass_cache: bool = False,
        date_gt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        if date_gt:
            params["date>"] = date_gt
        if bypass_cache:
            return await self._fetch_live("car_data", params)
        return await self._fetch_cached("car_data", params)

    async def get_team_radio(self, session_key: int) -> List[Dict[str, Any]]:
        return await self._fetch_cached("team_radio", {"session_key": session_key})

    async def get_laps(self, session_key: int, driver_number: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_cached("laps", params)

    async def get_stints(self, session_key: int, driver_number: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        return await self._fetch_cached("stints", params)

    async def get_positions(
        self,
        session_key: int,
        driver_number: Optional[int] = None,
        bypass_cache: bool = False,
        date_gt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"session_key": session_key}
        if driver_number is not None:
            params["driver_number"] = driver_number
        if date_gt:
            params["date>"] = date_gt
        if bypass_cache:
            return await self._fetch_live("position", params)
        return await self._fetch_cached("position", params)


