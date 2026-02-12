from azure.storage.blob import BlobServiceClient
import pandas as pd
import io
import os

def load_csv_from_blob(container: str, blob_name: str)-> pd.DataFrame:
    """Download a CSV from Azure Blob Storage into a DataFrame."""
    conn_str = os.getenv("AZURE_STORAGE_CONNECTON_STRING")
    client = BlobServiceClient.from_connection_string(conn_str)
    blob = client.get_blob_client(container=container, blob=blob_name)
    data = blob.download_blob().readall()
    return pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)