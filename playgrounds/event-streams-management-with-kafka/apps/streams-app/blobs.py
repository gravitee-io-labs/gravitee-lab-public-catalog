"""Azurite, where the gateway offloads large messages: what is in it, so that a page can show a record's pointer is real."""
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient

from settings import Settings


def container(settings: Settings):
    service = BlobServiceClient.from_connection_string(settings.blob_connection, connection_timeout=3, read_timeout=5)
    return service.get_container_client(settings.blob_container)


def ensure(settings: Settings) -> None:
    """The container the gateway writes to exists before the first large order."""
    try:
        container(settings).create_container()
    except ResourceExistsError:
        pass


def listing(settings: Settings) -> list[dict]:
    """The blobs, newest first: name, size and when."""
    found = [{"name": b.name, "size": b.size, "created": b.creation_time.isoformat() if b.creation_time else ""}
             for b in container(settings).list_blobs()]
    return sorted(found, key=lambda b: b["created"], reverse=True)[:20]


def preview(settings: Settings, name: str, length: int = 240) -> dict:
    blob = container(settings).get_blob_client(name)
    size = blob.get_blob_properties().size
    head = blob.download_blob(offset=0, length=min(length, size)).readall()
    return {"name": name, "size": size, "head": head.decode("utf-8", errors="replace")}
