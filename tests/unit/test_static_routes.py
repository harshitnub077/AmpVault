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


@pytest.mark.asyncio
async def test_homepage():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert "Ampvault" in r.text
        assert "Institutional Solar Escrow" in r.text


@pytest.mark.asyncio
async def test_static_css_and_assets():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r_css = await client.get("/static/styles.css")
        assert r_css.status_code == 200
        assert "amp-modal-card" in r_css.text


@pytest.mark.asyncio
async def test_escrow_simulator_markup_present():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/")
        assert r.status_code == 200
        assert "demoModal" in r.text
        assert "simStateBadge" in r.text
