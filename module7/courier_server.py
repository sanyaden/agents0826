"""
М5 — той самий сервер, що на слайді 14. Мінімум, який уже працює.

П'ятнадцять рядків, дві функції, жодного фреймворка агентів. Це
скелет для воркшопу: замініть тіла функцій на виклики свого API — і
сервер готовий.

Порівняйте з tracking_mcp.py: там той самий FastMCP, але поверх
справжнього domain/backend.py, з реальними правилами й помилками.

    python courier_server.py                              # stdio, чекає клієнта
    npx @modelcontextprotocol/inspector python courier_server.py
    claude mcp add courier -- python courier_server.py
"""

# На слайді написано FastMCP — так це називалось у SDK 1.x. У 2.0 клас
# перейменували на MCPServer, API лишився той самий. Два рядки нижче
# роблять файл робочим на обох версіях.
try:
    from mcp.server import MCPServer as _Server          # SDK >= 2.0
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server    # SDK 1.x

mcp = _Server("courier")


@mcp.tool()
def track_parcel(barcode: str) -> str:
    """Статус посилки за штрихкодом."""      # цей рядок читає модель
    return f"{barcode}: у дорозі, сортувальний центр Київ"


@mcp.tool()
def offices_nearby(city: str) -> list[str]:
    """Найближчі відділення у місті."""
    return [f"{city}, вул. Хрещатик 22", f"{city}, пр. Науки 5"]


if __name__ == "__main__":
    mcp.run()   # stdio; або mcp.run(transport="streamable-http") для remote
