import httpx
import pytest
from src.main import app

@pytest.mark.asyncio
async def test_favicon_endpoints():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r_ico = await client.get("/favicon.ico")
        assert r_ico.status_code == 200
        r_svg = await client.get("/favicon.svg")
        assert r_svg.status_code == 200
