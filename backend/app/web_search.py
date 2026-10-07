import logging
import os
from urllib.parse import urlsplit

from ddgs import DDGS

logger = logging.getLogger("uvicorn.error")

def handle_search(text):
    parts = text.strip().split(maxsplit=1)

    if not parts or parts[0].lower() != "/buscar":
        return None

    enabled = os.getenv("WEB_SEARCH_ENABLED", "false").lower() == "true"
    if not enabled:
        return "La búsqueda web está desactivada."

    if len(parts) < 2 or not parts[1].strip():
        return "Escribe /buscar seguido de lo que necesitas encontrar."

    query = parts[1].strip()
    if len(query) > 400:
        return "Acorta la búsqueda a un máximo de 400 caracteres."

    try:
        results = DDGS(timeout=10).text(query, max_results=3)
    except Exception as error:
        logger.warning("Búsqueda web fallida: %s", type(error).__name__)
        return "La búsqueda falló en este momento. Puedes intentarlo más tarde."

    entries = []

    for result in results:
        url = str(result.get("href", ""))
        if urlsplit(url).scheme not in {"http", "https"}:
            continue

        title = " ".join(str(result.get("title", "")).split())[:160]
        snippet = " ".join(str(result.get("body", "")).split())[:400]

        entries.append(
            f"{len(entries) + 1}. {title}\n"
            f"Extracto: {snippet or 'Sin extracto disponible.'}\n"
            f"{url}"
        )

    if not entries:
        return "No encontré resultados para esa búsqueda. Prueba con otras palabras."

    return (
        "Encontré estos resultados:\n\n"
        + "\n\n".join(entries)
        + "\n\nSon extractos del buscador; no he revisado las páginas completas."
    )
