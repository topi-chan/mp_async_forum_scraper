import requests

from config import ARCHIVE_FILENAME

proxies = {
    "http": "socks5h://localhost:9050",
    "https": "socks5h://localhost:9050",
}

file_path = ARCHIVE_FILENAME
with open(file_path, "rb") as file_to_upload:
    response = requests.post(
        "https://file.io", files={"file": file_to_upload}, proxies=proxies
    )

if response.status_code == 200:
    print("File uploaded successfully!")
    print("Download link:", response.json()["link"])
else:
    print("Failed to upload. Status:", response.status_code)
