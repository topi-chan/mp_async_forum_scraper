import asyncio
import logging
import os
import random
import time
from multiprocessing import Manager, Pool, Queue

import aiohttp
import aiohttp_socks
from bs4 import BeautifulSoup

from config import (BASE_URL, EXCLUDE_SUB_SUBFORUM_TOPIC,
                    EXCLUDE_SUB_SUBFORUM_URL, EXCLUDED_TOPIC_NAMES,
                    MAIN_FORUM_URL, NEXT_BUTTON, SUB_SUBFORUM_NAME,
                    SUBFORUM_LINK, SUBFORUM_NAME)
from setup import (get_random_user_agent_and_referrer, listener_process,
                   setup_logging)
from utils import retry, save_topics, start_tor_service

# Start Tor service before the script runs
try:
    start_tor_service()
except Exception as e:
    print(f"Failed to start Tor after retries: {e}")
    quit()


class ForumScraper:
    """
    A class to scrape forum data asynchronously.

    Attributes:
        main_forum_url (str): URL of the main forum.
        base_url (str): Base URL for constructing full links.
        headers (list): List of headers for HTTP requests.
        semaphore (asyncio.Semaphore): Semaphore to limit concurrency.
        subforum_name (str): CSS selector for subforum names.
        sub_subforum_name (str): CSS selector for sub-subforum names.
        exclude (tuple): Tuple of topic names to exclude.
        exclude_sub_subforum_url (tuple): Tuple of sub-subforum URLs to exclude.
        exclude_sub_subforum_name (tuple): Tuple of sub-subforum names to exclude.
        next_button (str): CSS selector for the "Next" button.
        subforum_link (str): CSS selector for subforum links.
    """

    def __init__(
        self,
        main_forum_url: str = MAIN_FORUM_URL,
        base_url: str = BASE_URL,
        headers: list = None,
        concurrency_limit=100,  # Set value equal to the number of fetched headers
        subforum_name=SUBFORUM_NAME,
        sub_subforum_name: str = SUB_SUBFORUM_NAME,
        exclude: tuple = EXCLUDED_TOPIC_NAMES,
        exclude_sub_subforum_url: tuple = EXCLUDE_SUB_SUBFORUM_URL,
        exclude_sub_subforum_name: tuple = EXCLUDE_SUB_SUBFORUM_TOPIC,
        next_button: str = NEXT_BUTTON,
        subforum_link: str = SUBFORUM_LINK,
    ):
        """
        Initialize the ForumScraper with the given parameters.

        :param main_forum_url: URL of the main forum.
        :param base_url: Base URL for constructing full links.
        :param headers: List of headers for HTTP requests.
        :param concurrency_limit: Limit for concurrent requests.
        :param subforum_name: CSS selector for subforum names.
        :param sub_subforum_name: CSS selector for sub-subforum names.
        :param exclude: Tuple of topic names to exclude.
        :param exclude_sub_subforum_url: Tuple of sub-subforum URLs to exclude.
        :param exclude_sub_subforum_name: Tuple of sub-subforum names to exclude.
        :param next_button: CSS selector for the "Next" button.
        :param subforum_link: CSS selector for subforum links.
        """
        self.main_forum_url = main_forum_url
        self.base_url = base_url
        self.subforum_links = []
        self.sub_subforum_links = []
        self.headers = headers or []
        self.semaphore = asyncio.Semaphore(concurrency_limit)  # Limit concurrency
        self.subforum_name = subforum_name
        self.sub_subforum_name = sub_subforum_name
        self.exclude = exclude
        self.exclude_sub_subforum_url = exclude_sub_subforum_url
        self.exclude_sub_subforum_name = exclude_sub_subforum_name
        self.next_button = next_button
        self.subforum_link = subforum_link

    async def prefetch_headers(self, count: int = 100) -> None:
        """
        Fetch random headers asynchronously to mimic different user agents.

        :param count: Number of headers to fetch.
        """
        logging.info(f"Fetching {count} random headers...")
        tasks = [self.fetch_random_header() for _ in range(count)]
        self.headers = await asyncio.gather(*tasks)
        logging.info(f"Fetched {len(self.headers)} headers.")

    @staticmethod
    async def fetch_random_header() -> dict:
        """
        Fetch a random header asynchronously.

        :return: A dictionary containing a random user agent and referrer.
        """
        return await asyncio.to_thread(get_random_user_agent_and_referrer)

    def get_random_header(self) -> dict:
        """
        Get a random header from the pre-fetched headers.

        :return: A dictionary containing a random user agent and referrer.
        """
        if self.headers:
            return random.choice(self.headers)
        return get_random_user_agent_and_referrer()

    @retry((aiohttp.ClientError, asyncio.TimeoutError, Exception))
    async def fetch(self, session: aiohttp.ClientSession, url: str) -> str | None:
        """
        Fetch the HTML content of a given URL.

        :param session: The aiohttp client session.
        :param url: The URL to fetch.
        :return: The HTML content of the URL or None if excluded.
        """
        for i in self.exclude_sub_subforum_url:
            if i in url:
                logging.debug(f"Skipping sub-subforum with {i}: {url}")
                return None
        headers = self.get_random_header()
        logging.debug(f"Fetching URL: {url} with headers: {headers}")
        async with self.semaphore:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.text()

    async def extract_subforum_links(self, session: aiohttp.ClientSession) -> None:
        """
        Extract links to subforums from the main forum page.

        :param session: The aiohttp client session.
        """
        try:
            logging.debug(f"Extracting subforum links from: {self.main_forum_url}")
            html = await self.fetch(session, self.main_forum_url)
            soup = BeautifulSoup(html, "html.parser")
            subforums = soup.select(self.subforum_name)
            for subforum in subforums:
                title = subforum.text.strip()
                for i in self.exclude:
                    if i in title:
                        logging.debug(f"Skipping subforum with '{i}': {title}")
                        continue
                link = subforum["href"]
                if not link.startswith("http"):
                    link = f"{self.base_url}{link}"
                self.subforum_links.append((title, link))
                logging.debug(f"Found subforum: {title} -> {link}")
        except Exception as e:
            logging.error(f"Error extracting subforums: {e}")

    async def extract_sub_subforum_links(
        self, session: aiohttp.ClientSession, subforum_url: str
    ) -> list:
        """
        Extract links to sub-subforums from a subforum page.

        :param session: The aiohttp client session.
        :param subforum_url: The URL of the subforum.
        :return: A list of tuples containing sub-subforum titles and links.
        """
        sub_subforum_links = []
        try:
            logging.debug(f"Extracting sub-subforum links from: {subforum_url}")
            html = await self.fetch(session, subforum_url)
            soup = BeautifulSoup(html, "html.parser")
            sub_subforums = soup.select(self.sub_subforum_name)
            for sub_subforum in sub_subforums:
                title = sub_subforum.text.strip()
                for i in self.exclude_sub_subforum_name:
                    if i in title:
                        logging.debug(f"Skipping sub-subforum with {i}: {title}")
                        continue
                link = sub_subforum["href"]
                if not link.startswith("http"):
                    link = f"{self.base_url}{link}"
                sub_subforum_links.append((title, link))
                logging.debug(f"Found sub-subforum: {title} -> {link}")
        except Exception as e:
            logging.error(f"Error extracting sub-subforums from {subforum_url}: {e}")
        return sub_subforum_links

    async def scrape_subforum(
        self, session: aiohttp.ClientSession, subforum_name: str, subforum_url: str
    ) -> list:
        """
        Scrape topics from a given subforum, handling pagination.

        :param session: The aiohttp client session.
        :param subforum_name: The name of the subforum.
        :param subforum_url: The URL of the subforum.
        :return: A list of tuples containing subforum name, topic title, and link.
        """
        topics_data = []
        try:
            logging.debug(f"Scraping subforum: {subforum_url}")
            html = await self.fetch(session, subforum_url)
            soup = BeautifulSoup(html, "html.parser")
            topics = soup.select(self.subforum_link)
            for topic in topics:
                title = topic.text.strip()
                link = topic["href"]
                topics_data.append((subforum_name, title, link))
            next_button = soup.select_one(self.next_button)
            if next_button:
                next_page_url = next_button.get("href")
                if not next_page_url.startswith("http"):
                    next_page_url = f"{self.base_url}{next_page_url}"
                logging.debug(f"Navigating to next page: {next_page_url}")
                topics_data.extend(
                    await self.scrape_subforum(session, subforum_name, next_page_url)
                )
        except Exception as e:
            logging.error(f"Error scraping subforum {subforum_url}: {e}")
        return topics_data


async def scrape_subforum_concurrently(
    scraper: ForumScraper, subforum_title: str, subforum_link: str
) -> None:
    """
    Orchestrate the scraping process for a subforum, including both general topics and sub-subforums.

    :param scraper: The ForumScraper instance.
    :param subforum_title: The title of the subforum.
    :param subforum_link: The URL of the subforum.
    """
    async with aiohttp.ClientSession(
        connector=aiohttp_socks.ProxyConnector.from_url("socks5://127.0.0.1:9050")
    ) as session:
        sub_subforum_links = await scraper.extract_sub_subforum_links(
            session, subforum_link
        )
        all_topics = []
        tasks = [
            scraper.scrape_subforum(session, title, link)
            for title, link in sub_subforum_links
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            all_topics.extend(result)
        await save_topics(subforum_title, all_topics)


async def run_scraping_for_subforum(subforum: tuple, headers: list) -> None:
    """
    Run the scraping process for a subforum asynchronously.

    :param subforum: A tuple containing the subforum title and link.
    :param headers: List of headers for HTTP requests.
    """
    scraper = ForumScraper(headers=headers)
    await scrape_subforum_concurrently(scraper, subforum[0], subforum[1])


def run_scraping_in_process(subforum: tuple, headers: list) -> None:
    """
    Run the scraping process for a subforum within a separate process.

    :param subforum: A tuple containing the subforum title and link.
    :param headers: List of headers for HTTP requests.
    """
    asyncio.run(run_scraping_for_subforum(subforum, headers))


def run_multiprocessing_scraping(subforum_links: list, headers: list) -> None:
    """
    Use multiprocessing to scrape multiple subforums concurrently.

    :param subforum_links: List of subforum links to scrape.
    :param headers: List of headers for HTTP requests.
    """
    num_processors = min(os.cpu_count(), len(subforum_links))
    logging.info(f"Using {num_processors} processors for scraping.")
    queue = Queue()
    listener = listener_process(queue)
    with Pool(num_processors, initializer=setup_logging, initargs=(queue,)) as pool:
        pool.starmap(
            run_scraping_in_process,
            [(subforum, headers) for subforum in subforum_links],
        )
    listener.stop()


async def run_scraping() -> None:
    """
    Main function to run the scraping process.

    Prefetch headers, extract subforum links, and run multiprocessing scraping.
    """
    scraper = ForumScraper()
    await scraper.prefetch_headers(count=100)
    async with aiohttp.ClientSession(
        connector=aiohttp_socks.ProxyConnector.from_url("socks5://127.0.0.1:9050")
    ) as session:
        await scraper.extract_subforum_links(session)
    if scraper.subforum_links:
        manager = Manager()
        headers = manager.list(scraper.headers)
        run_multiprocessing_scraping(scraper.subforum_links, headers)


if __name__ == "__main__":
    """
    Entry point of the script.

    Set up logging, start the scraping process, and measure execution time.
    """
    setup_logging()
    start_time = time.perf_counter()
    asyncio.run(run_scraping())
    end_time = time.perf_counter()
    total_time = end_time - start_time
    minutes, seconds = divmod(total_time, 60)
    logging.debug(
        f"Scraping completed in {int(minutes)} minutes and {seconds:.2f} seconds."
    )
