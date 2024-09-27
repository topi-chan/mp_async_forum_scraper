import requests

from config import ARCHIVE_FILENAME, TOR_PROXY_URL

proxies: dict[str, str] = {
    "http": TOR_PROXY_URL,
    "https": TOR_PROXY_URL,
}

file_path: str = ARCHIVE_FILENAME
with open(file_path, "rb") as file_to_upload:
    response: requests.Response = requests.post(
        "https://file.io", files={"file": file_to_upload}, proxies=proxies
    )

if response.status_code == 200:
    print("File uploaded successfully!")
    print("Download link:", response.json()["link"])
else:
    print("Failed to upload. Status:", response.status_code)
