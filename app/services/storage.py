"""Download de anexos do MinIO (mesmo storage usado pelo nexusgov-api)."""

import logging
from functools import lru_cache
from urllib.parse import urlparse

from minio import Minio

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache()
def get_minio_client() -> Minio:
    settings = get_settings()
    parsed = urlparse(settings.s3_endpoint)
    endpoint = parsed.netloc or parsed.path
    return Minio(
        endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=parsed.scheme == "https",
    )


def baixar_anexo(arquivo_key: str) -> bytes:
    """Baixa o objeto do bucket geral. Levanta exceção se não existir."""
    settings = get_settings()
    client = get_minio_client()
    response = client.get_object(settings.s3_bucket_geral, arquivo_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
