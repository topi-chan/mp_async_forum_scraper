import functools
import logging
import os
import re
import subprocess
import time
import unicodedata

import aiofiles

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


async def save_topics(
    subforum_name: str, all_topics: list[tuple[str, str, str]]
) -> None:
    """
    Save scraped topics to a file asynchronously with uniqueness and sorting.

    :param subforum_name: The name of the subforum.
    :param all_topics: A list of tuples containing subforum, title, and link.
    """
    unique_topics = []
    seen_titles = set()

    # Filter out duplicate topics based on their title (case-insensitive)
    for subforum, title, link in all_topics:
        title_lower = title.lower()
        if title_lower not in seen_titles:
            unique_topics.append((subforum, title, link))
            seen_titles.add(title_lower)

    # Sort topics by subforum and title (Polish alphabetical order)
    sorted_topics = sorted(unique_topics, key=lambda x: (x[0], polish_sort_key(x[1])))

    # Ensure the 'files' directory exists
    os.makedirs("files", exist_ok=True)

    # Sanitize the subforum name to avoid non-ASCII characters
    sanitized_subforum_name = sanitize_filename(subforum_name)
    file_path = f"files/{sanitized_subforum_name.replace(' ', '_').lower()}.txt"

    # Write topics to the file asynchronously
    async with aiofiles.open(file_path, "a", encoding="utf-8") as file:
        current_subforum = None
        for subforum, title, link in sorted_topics:
            # Write subforum header if we have changed subforum
            if subforum != current_subforum:
                if current_subforum is not None:
                    await file.write("\n")  # Add a new line between subforums
                await file.write(f"\n[{subforum}]\n")  # Write subforum header
                current_subforum = subforum

            # Write each topic under the subforum
            await file.write(f"[*][url={link}]{title}[/url]\n")

    logging.info(f"All topics saved to {file_path}.")
