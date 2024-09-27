import logging
import random
import sys
from logging import StreamHandler
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from multiprocessing import Queue
from tempfile import mkdtemp

import aiohttp
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService

from config import TOR_PROXY_URL

# Hardcoded fallback User-Agent and Referrers
user_agents = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.152 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:90.0) Gecko/20100101 Firefox/90.0",
    "Mozilla/5.0 (Windows NT 6.3; Win64; x64; Trident/7.0; rv:11.0) like Gecko",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:92.0) Gecko/20100101 Firefox/92.0",
    "Mozilla/5.0 (Linux; U; Android 10; en-US; SM-G960U Build/QP1A.190711.020) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.117 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; ARM; Surface Pro X) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59 Safari/537.36",
)
referers = (
    "https://www.google.com",
    "https://www.bing.com",
    "https://duckduckgo.com",
)


def setup_browser():
    """
    Setup Selenium browser with specific options and preferences to run
    in lightweight mode, also on AWS Lambda container.

    :return: Configured Selenium WebDriver instance.
    """
    options = webdriver.ChromeOptions()
    options.binary_location = "/opt/chrome-linux64/chrome"
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-first-run")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-web-security")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280x1696")
    options.add_argument("--single-process")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-dev-tools")
    options.add_argument("--no-zygote")
    options.add_argument(f"--user-data-dir={mkdtemp()}")
    options.add_argument(f"--data-path={mkdtemp()}")
    options.add_argument(f"--disk-cache-dir={mkdtemp()}")
    options.add_argument("--remote-debugging-port=9222")

    # Fetch random User-Agent and Referer
    user_agent, referer = get_random_user_agent_and_referrer()
    options.add_argument(f"user-agent={user_agent}")
    options.add_argument(f"referer={referer}")
    options.add_argument(f"--proxy-server={TOR_PROXY_URL}")

    prefs = {
        "download.default_directory": mkdtemp(),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing_for_trusted_sources_enabled": False,
        "safebrowsing.enabled": False,
    }
    options.add_experimental_option("prefs", prefs)

    svc = ChromeService(executable_path="/opt/chromedriver-linux64/chromedriver")
    return webdriver.Chrome(service=svc, options=options)


def get_random_user_agent_and_referrer():
    """
    Fetch random User-Agent and Referer from an API using Tor.

    :return: Dictionary containing User-Agent and Referer.
    """
    try:
        # Set up proxies to use Tor
        proxies = {
            "http": TOR_PROXY_URL,
            "https": TOR_PROXY_URL,
        }

        # Fetch a random user-agent using an external API via Tor
        response = requests.get("https://api.apicagent.com", proxies=proxies).json()
        user_agent = response.get(
            "user-agent", random.choice(user_agents)
        )  # Fallback to hardcoded User-Agent
        referer = random.choice(referers)
        logging.debug(f"Random User-Agent fetched: {user_agent}, Referer: {referer}")
    except Exception as e:
        logging.error(
            f"Failed to fetch random User-Agent from API over Tor, falling back to default. Error: {e}"
        )
        user_agent = random.choice(user_agents)
        referer = random.choice(referers)

    return {"User-Agent": user_agent, "Referer": referer}


def setup_logging(queue: Queue = None, level=logging.DEBUG) -> None:
    """
    Setup logging configuration with optional multiprocessing queue.

    :param queue: Optional multiprocessing queue for logging.
    :param level: Logging level to set
    """
    log_format = "%(asctime)s [PID: %(process)d] %(levelname)s: %(message)s"
    root_logger = logging.getLogger()

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    if queue:
        queue_handler = QueueHandler(queue)
        root_logger.setLevel(level)
        root_logger.addHandler(queue_handler)
    else:
        console_handler = StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        root_logger.setLevel(level)
        root_logger.addHandler(console_handler)

    selenium_logger = logging.getLogger("selenium")
    selenium_logger.setLevel(logging.WARNING)
    urllib3_logger = logging.getLogger("urllib3")
    urllib3_logger.setLevel(logging.WARNING)


def listener_process(queue: Queue, log_file: str = "scraping.log") -> QueueListener:
    """
    Listener process to handle logs from multiple processes.

    :param queue: Multiprocessing queue for logging.
    :param log_file: Path to the log file.
    :return: Configured QueueListener instance.
    """
    listener_handler = logging.FileHandler(log_file)
    listener_handler.setLevel(logging.DEBUG)
    listener_handler.setFormatter(
        logging.Formatter("%(asctime)s [PID: %(process)d] %(levelname)s: %(message)s")
    )

    console_handler = StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [PID: %(process)d] %(levelname)s: %(message)s")
    )

    listener = QueueListener(queue, listener_handler, console_handler)
    listener.start()
    return listener


async def async_get_random_user_agent_and_referrer(
    session: aiohttp.ClientSession,
) -> dict:
    """
    Fetch a random User-Agent and Referer using an external API over Tor asynchronously if needed (backup func).

    :param session: The aiohttp client session.
    :return: Dictionary containing User-Agent and Referer.
    """
    try:
        async with session.get("https://api.apicagent.com") as response:
            data = await response.json()
            user_agent = data.get("user-agent", random.choice(user_agents))  # Fallback
            referer = random.choice(referers)
            logging.debug(
                f"Random User-Agent fetched: {user_agent}, Referer: {referer}"
            )
    except Exception as e:
        logging.error(
            f"Failed to fetch random User-Agent from API over Tor, using fallback. Error: {e}"
        )
        user_agent = random.choice(user_agents)
        referer = random.choice(referers)

    return {"User-Agent": user_agent, "Referer": referer}


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
