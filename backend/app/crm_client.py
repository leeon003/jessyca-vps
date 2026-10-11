import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

CRM_URL = "http://127.0.0.1:8000/api/interno/productos"
TOKEN_FILE = Path("/home/admin/jessyca-private/catalog-token")
logger = logging.getLogger(__name__)


def consultar_productos():
    try:
        token = TOKEN_FILE.read_text().strip()

        request = urllib.request.Request(
            CRM_URL,
            headers={"X-Catalog-Token": token},
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response)

        productos = data.get("productos", [])

        if not isinstance(productos, list):
            raise ValueError("Catálogo inválido")

        return productos

    except (
        OSError,
        ValueError,
        urllib.error.URLError,
    ) as error:
        logger.warning(
            "No se pudo consultar el catálogo: %s",
            type(error).__name__,
        )
        return None
