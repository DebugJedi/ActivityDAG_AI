from __future__ import annotations

import io
import os
from typing import List, Optional

import pandas as pd
from azure.storage.blob import BlobServiceClient


def _blob_service(conn_str: Optional[str] = None) -> BlobServiceClient:
    conn_str = conn_str or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    if not conn_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not set.")
    return BlobServiceClient.from_connection_string(conn_str)


def list_blob_names(container: str, prefix: str = "", conn_str: Optional[str] = None) -> List[str]:
    svc = _blob_service(conn_str)
    cc = svc.get_container_client(container)
    return [b.name for b in cc.list_blobs(name_starts_with=prefix)]


def load_csv_from_blob(container: str, blob_name: str, conn_str: Optional[str] = None) -> pd.DataFrame:
    svc = _blob_service(conn_str)
    blob = svc.get_blob_client(container=container, blob=blob_name)
    data = blob.download_blob().readall()
    df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    df = df.replace({"": pd.NA})
    return df
