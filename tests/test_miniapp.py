"""The Mini App is served by the same FastAPI app as the API."""

from httpx import AsyncClient

from app.main import MINIAPP_INDEX


async def test_index_is_served_at_app(client: AsyncClient) -> None:
    response = await client.get("/app")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "telegram-web-app.js" in response.text


async def test_index_is_served_at_app_slash(client: AsyncClient) -> None:
    """`html=True` on the mount, so the directory root is the page too."""
    response = await client.get("/app/")

    assert response.status_code == 200
    assert "telegram-web-app.js" in response.text


async def test_the_page_needs_no_authentication(client: AsyncClient) -> None:
    """The page is public; every call it makes afterwards is signed."""
    assert (await client.get("/app")).status_code == 200


async def test_the_page_is_a_single_file(client: AsyncClient) -> None:
    """No build step, no external CSS or JS beyond Telegram's own script."""
    page = (await client.get("/app")).text

    assert page.count("<script") == 2  # telegram-web-app.js and the inline app
    assert "<link" not in page
    assert MINIAPP_INDEX.is_file()
