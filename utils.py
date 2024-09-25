import functools
import logging
import os
import re
import subprocess
import sys
import tarfile
import time
import unicodedata
from logging.handlers import RotatingFileHandler

import aiofiles

from config import ARCHIVE_NAME, FILES_DIR, RESULTS_DIR

# Define Polish alphabet order
polish_alphabet = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
alphabet_order = {letter: index for index, letter in enumerate(polish_alphabet)}


def polish_sort_key(text: str) -> list[int]:
    """
    Sort key function to handle sorting of Polish characters correctly.

    :param text: The text to be sorted.
    :return: A list of integers representing the order of characters in the text.
    """
    # Normalize the text to NFKD form to separate accents and base characters
    normalized = unicodedata.normalize("NFKD", text.lower())
    # Only consider alphabet characters (ignore diacritics and accents)
    return [alphabet_order.get(c, 999) for c in normalized if c.isalpha()]


def save_to_single_file(
    main_subforum_name: str, all_topics: list[tuple[str, str, str]]
) -> None:
    """
    Save all topics to a single file, ensuring uniqueness and sorting.

    :param main_subforum_name: The name of the main subforum.
    :param all_topics: A list of tuples containing subforum, title, and link.
    """
    unique_topics = []
    seen_titles = set()

    for subforum, title, link in all_topics:
        title_lower = title.lower()
        if title_lower not in seen_titles:
            unique_topics.append((subforum, title, link))
            seen_titles.add(title_lower)

    # Sort topics with Polish alphabetical order
    sorted_topics = sorted(unique_topics, key=lambda x: (x[0], polish_sort_key(x[1])))

    os.makedirs("files", exist_ok=True)
    file_path = f"files/{main_subforum_name.replace(' ', '_').lower()}.txt"

    with open(file_path, "a", encoding="utf-8") as file:
        current_subforum = None
        for subforum, title, link in sorted_topics:
            if subforum != current_subforum:
                if current_subforum is not None:
                    file.write("\n")
                file.write(f"\n[{subforum}]\n")
                current_subforum = subforum
            file.write(f"[*][url={link}]{title}[/url]\n")

    logging.info(f"All topics saved to {file_path}.")


def retry(
    exceptions: tuple[type[BaseException], ...],
    tries: int = 3,
    delay: int = 2,
    backoff: float = 1.5,
) -> callable:
    """
    Retry decorator to retry the decorated function in case of specified exceptions.

    :param exceptions: A tuple of exception types to catch and retry on.
    :param tries: Number of attempts.
    :param delay: Initial delay between retries.
    :param backoff: Multiplier to increase the delay between each retry.
    :return: The decorated function with retry logic.
    """

    def decorator(func: callable) -> callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    logging.warning(
                        f"{func.__name__} failed with {e}, retrying in {_delay} seconds..."
                    )
                    time.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
            return func(*args, **kwargs)  # Last try

        return wrapper

    return decorator


@retry((subprocess.CalledProcessError,), tries=5, delay=2)
def start_tor_service() -> None:
    """
    Start the Tor service with retries, but only if it's not already running.
    """
    # Check if Tor is already running
    result = subprocess.run(
        ["service", "tor", "status"], capture_output=True, text=True
    )
    if "is running" in result.stdout:
        print("Tor is already running.")
    else:
        print("Starting Tor service...")
        subprocess.run(["service", "tor", "start"], check=True)


def sanitize_filename(filename: str) -> str:
    """
    Remove or replace non-ASCII characters from the filename.

    :param filename: The original filename.
    :return: The sanitized filename.
    """
    # Replace non-ASCII characters with an empty string
    return re.sub(r"[^\x00-\x7F]+", "", filename)


def wipe_files_directory() -> None:
    """
    Wipe the contents of the FILES_DIR directory to avoid appending to old data.
    """
    files_dir = "files"
    if os.path.exists(files_dir):
        for file in os.listdir(files_dir):
            file_path = os.path.join(files_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                logging.error(f"Error while deleting file {file_path}: {e}")
    else:
        os.makedirs(files_dir)  # Create the 'files/' directory if it doesn't exist


async def save_topics(
    subforum_name: str, all_topics: list[tuple[str, str, str]]
) -> str:
    """
    Save scraped topics to a file asynchronously with uniqueness and sorting.
    :param subforum_name: The name of the subforum.
    :param all_topics: A list of tuples containing subforum, title, and link.
    :return: The path of the saved file.
    """
    unique_topics = []
    seen_titles = set()

    # Filter out duplicate topics based on their title (case-insensitive)
    for subforum, title, link in all_topics:
        title_lower = title.lower()
        if title_lower not in seen_titles:
            unique_topics.append((subforum, title, link))
            seen_titles.add(title_lower)

    # Sort topics by subforum and title (case-insensitive)
    sorted_topics = sorted(unique_topics, key=lambda x: (x[0], x[1].lower()))

    # Sanitize the subforum name to avoid non-ASCII characters
    sanitized_subforum_name = sanitize_filename(subforum_name)
    file_path = f"{FILES_DIR}/{sanitized_subforum_name}.txt"

    # Write topics to the file asynchronously
    async with aiofiles.open(file_path, "w", encoding="utf-8") as file:
        current_subforum = None
        for subforum, title, link in sorted_topics:
            if subforum != current_subforum:
                if current_subforum is not None:
                    await file.write("\n")  # Add a new line between subforums
                await file.write(f"\n[{subforum}]\n")
                current_subforum = subforum

            # Write each topic under the subforum
            await file.write(f"[*][url={link}]{title}[/url]\n")

    logging.info(f"All topics saved to {file_path}.")
    return file_path


def create_tar_archive(results_dir: str = RESULTS_DIR) -> str:
    """
    Create a .tar archive of the files/ directory and store it in the specified results directory.
    :param results_dir: Directory to store the archive.
    :return: The path of the created tar archive.
    """
    os.makedirs(results_dir, exist_ok=True)
    archive_path = os.path.join(results_dir, ARCHIVE_NAME) # TODO: inspect if not .tar in filename needed

    # Create the tar archive
    with tarfile.open(archive_path, "w") as tar:
        tar.add(FILES_DIR, arcname=os.path.basename(FILES_DIR))

    logging.info(f"Created tar archive at {archive_path}")
    return archive_path


def setup_api_logging():
    """
    Set up logging for the FastAPI application with log rotation.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Create handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        "app.log", maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.INFO)

    # Create formatters and add them to the handlers
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Clear existing handlers, and add the new handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
