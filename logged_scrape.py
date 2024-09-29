import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
import aiohttp_socks
import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import (ACTION_ELEMENT, ACTIVITY_CLASS, DATE_ELEMENT,
                    FORUM_PASSWORD, FORUM_USERNAME, GROUP_ID, GROUP_URL,
                    LOGIN_URL, LOGOUT_URL, LOGS_URL, MAIN_FORUM_URL,
                    MEMBERS_CLASS, MEMBERS_DIVS, TOR_PROXY_URL)
from scrape import ForumScraper
from setup import setup_logging, setup_browser, get_random_user_agent_and_referrer
from utils import async_retry, parse_date, get_cookies_from_selenium

setup_logging()


class LoggedInForumScraper(ForumScraper):
    def __init__(self, username: str, password: str, *args, **kwargs) -> None:
        """
        Initialize the LoggedInForumScraper.

        Args:
            username (str): The username for the forum.
            password (str): The password for the forum.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(
            main_forum_url=MAIN_FORUM_URL, base_url=MAIN_FORUM_URL, *args, **kwargs
        )
        # Initialize the browser with the random User-Agent
        self.browser = setup_browser()
        self.login_url: str = LOGIN_URL
        self.username: str = username
        self.password: str = password
        self.members: list[tuple[str, str]] = []
        self.logout: str = LOGOUT_URL
        self.group_url: str = GROUP_URL
        self.members_divs: str = MEMBERS_DIVS
        self.members_class: str = MEMBERS_CLASS
        self.group_id: int = GROUP_ID
        self.logs_url: str = LOGS_URL
        self.activity_class: str = ACTIVITY_CLASS
        self.action_element: str = ACTION_ELEMENT
        self.date_element: str = DATE_ELEMENT
        self.activities_df = pd.DataFrame(
            columns=["Moderator", "Action", "Date", "Details"]
        )

    def login(self):
        """
        Log in to the forum using Selenium and return the browser instance.
        """
        try:
            login_url = f"{self.main_forum_url}{self.login_url}"
            logging.info(f"Navigating to login URL: {login_url}")

            # Apply anti-detection measures before navigating to the page
            self.browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.navigator.chrome = {runtime: {}};
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
                """
            })

            self.browser.get(login_url)

            # Wait for the username field to be present
            wait = WebDriverWait(self.browser, 20)
            wait.until(EC.presence_of_element_located((By.ID, "username")))

            # Fill in the username and password fields
            username_field = self.browser.find_element(By.ID, "username")
            password_field = self.browser.find_element(By.ID, "password")
            username_field.clear()
            password_field.clear()

            # Using send_keys to simulate real typing
            username_field.send_keys(self.username)
            password_field.send_keys(self.password)

            # Click the login button
            login_button = self.browser.find_element(By.NAME, "login")
            login_button.click()

            # Wait for the logout link to confirm successful login
            wait.until(EC.presence_of_element_located(
                (By.XPATH, "//a[contains(@href, 'ucp.php?mode=logout')]")))

            logging.info("Logged in successfully using Selenium.")
            return self.browser
        except Exception as e:
            logging.error(f"Selenium login failed: {e}")
            # Capture screenshot and page source for debugging
            self.browser.save_screenshot('login_error.png')
            with open('login_error.html', 'w', encoding='utf-8') as f:
                f.write(self.browser.page_source)
            self.browser.quit()
            raise

    @async_retry((Exception,), tries=3, delay=4)
    async def get_group_members(
        self,
        session: aiohttp.ClientSession,
        group_id: int,
        start_indices: list[int] = (0, 15),
    ) -> None:
        """
        Fetch the list of group members and store them as a class attribute.

        Args:
            session (aiohttp.ClientSession): The aiohttp session to use for fetching members.
            group_id (int): The ID of the group to fetch members from.
            start_indices (list[int]): The start indices for pagination.

        Returns:
            None
        """
        try:
            members = []
            start_indices = start_indices  # Only fetch pages with defined start indices

            for start in start_indices:
                headers: dict = self.get_random_header()
                group_url: str = (
                    f"{self.base_url}{self.group_url}{group_id}&start={start}"
                )
                logging.info(f"Fetching group members from: {group_url}")

                async with session.get(group_url, headers=headers) as response:
                    response.raise_for_status()
                    html: str = await response.text()

                soup: BeautifulSoup = BeautifulSoup(html, "html.parser")

                # Find member elements
                member_divs = soup.find_all("div", class_=self.members_divs)

                if not member_divs:
                    logging.info(f"No members found on page starting at {start}")
                    raise Exception

                for member_div in member_divs:
                    username_elem = member_div.find("a", class_=self.members_class)
                    if username_elem:
                        username: str = username_elem.text.strip()
                        user_profile_url: str = username_elem["href"]
                        members.append((username, user_profile_url))

            logging.info(f"Found {len(members)} members in group {group_id}.")
            self.members = members  # Save members to class attribute

        except Exception as e:
            logging.error(f"Exception during getting group members: {e}")

    async def scrape_activity_logs(
        self,
        session: aiohttp.ClientSession,
        start_date: datetime,
        end_date: datetime,
    ) -> None:
        """
        Scrape moderator activity logs between start_date and end_date.
        """
        try:
            page = 0
            while True:
                headers = self.get_random_header()
                logs_url = f"{self.base_url}{self.logs_url}{page * 15}"
                logging.info(f"Fetching activity logs from: {logs_url}")

                async with session.get(logs_url, headers=headers) as response:
                    response.raise_for_status()
                    html = await response.text()

                soup = BeautifulSoup(html, "html.parser")

                # Find all activity rows
                activity_rows = soup.find_all("div", class_=self.activity_class)
                if not activity_rows:
                    logging.info("No more activities found.")
                    break  # No more activities

                for row in activity_rows:
                    # Extract action type
                    action_elem = row.find("div", class_=self.action_element)
                    action_type_elem = action_elem.find("strong")
                    if action_type_elem:
                        action_type = action_type_elem.text.strip()
                    else:
                        action_type = "Unknown"

                    # Extract moderator name
                    moderator_elem = row.find("a", class_=self.members_class)
                    if moderator_elem:
                        moderator_name = moderator_elem.text.strip()
                    else:
                        moderator_name = "Unknown"

                    # Extract date
                    date_elem = row.find_all("div", class_=self.date_element)[-1]
                    date_str = date_elem.text.strip()

                    # Parse date string
                    action_date = parse_date(date_str)
                    if action_date is None:
                        continue  # Skip if date parsing failed

                    # Check if date is within the desired range
                    if action_date < start_date:
                        logging.info("Reached the start date. Stopping.")
                        return  # Stop scraping as we've passed the desired date range

                    if action_date > end_date:
                        continue  # Skip actions beyond the end date

                    # Additional details
                    details = action_elem.get_text(separator=" ", strip=True)

                    # Append to DataFrame
                    action_data = {
                        "Moderator": moderator_name,
                        "Action": action_type,
                        "Date": action_date,
                        "Details": details,
                    }
                    self.activities_df = self.activities_df.append(
                        action_data, ignore_index=True
                    )

                # Move to the next page
                page += 1

        except Exception as e:
            logging.error(f"Exception during scraping activity logs: {e}")

    async def run(self) -> None:
        """
        Run the scraper to login and fetch group members and activities.
        """
        # Step 1: Use Selenium to log in and get cookies
        driver = await asyncio.to_thread(self.login)
        cookies = get_cookies_from_selenium(driver)
        driver.quit()  # Close the Selenium browser

        # Step 2: Use aiohttp session with the extracted cookies
        connector = aiohttp_socks.ProxyConnector.from_url(TOR_PROXY_URL)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Update session cookies
            session.cookie_jar.update_cookies(cookies)

            # Define the date range for scraping activities
            end_date = datetime.now()
            start_date = end_date - timedelta(days=1)  # Adjust the period as needed

            # Scrape moderator activities
            await self.scrape_activity_logs(
                session, start_date=start_date, end_date=end_date
            )

            # Process the activities DataFrame
            if not self.activities_df.empty:
                # Group actions by moderator and action type
                summary = (
                    self.activities_df.groupby(["Moderator", "Action"])
                    .size()
                    .reset_index(name="Count")
                )
                print(summary)
                # Optionally, save the summary to a text file
                # summary.to_csv('activity_summary.txt', sep='\t', index=False)
            else:
                print("No activities found in the specified date range.")


# Entry point
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    username: str = FORUM_USERNAME
    password: str = FORUM_PASSWORD

    scraper: LoggedInForumScraper = LoggedInForumScraper(username, password)
    asyncio.run(scraper.run())
