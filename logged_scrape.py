import asyncio
import logging

import aiohttp
import aiohttp_socks
from bs4 import BeautifulSoup

from config import (FORUM_PASSWORD, FORUM_USERNAME, GROUP_ID, GROUP_URL,
                    LOGIN_URL, LOGOUT_URL, MAIN_FORUM_URL, MEMBERS_CLASS,
                    MEMBERS_DIVS, TOR_PROXY_URL)
from scrape import ForumScraper
from setup import setup_logging
from utils import async_retry

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
        self.login_url: str = LOGIN_URL
        self.username: str = username
        self.password: str = password
        self.members: list[tuple[str, str]] = []
        self.logout: str = LOGOUT_URL
        self.group_url: str = GROUP_URL
        self.members_divs: str = MEMBERS_DIVS
        self.members_class: str = MEMBERS_CLASS
        self.group_id: int = GROUP_ID

    @async_retry((Exception,), tries=3, delay=8)
    async def login(self, session: aiohttp.ClientSession) -> bool:
        """
        Log in to the forum and maintain session cookies.

        Args:
            session (aiohttp.ClientSession): The aiohttp session to use for the login.

        Returns:
            bool: True if login was successful, False otherwise.
        """
        try:
            login_url = f"{self.main_forum_url}{self.login_url}"
            headers = self.get_random_header()
            logging.debug(
                f"Attempting to log in at URL: {login_url} with headers: {headers}"
            )

            # Step 1: GET the login page
            async with session.get(login_url, headers=headers) as response:
                response.raise_for_status()
                login_page_html = await response.text()
                logging.debug(f"Received login page with status {response.status}")
                logging.debug(f"Response headers: {response.headers}")
                logging.debug(
                    f"Session cookies after GET: {session.cookie_jar.filter_cookies(login_url)}"
                )

            # Save the login page HTML for debugging
            with open("login_page.html", "w", encoding="utf-8") as f:
                f.write(login_page_html)

            # Step 2: Parse the login page to extract hidden fields
            soup: BeautifulSoup = BeautifulSoup(login_page_html, "html.parser")
            login_form = soup.find("form", {"id": "login"})
            if not login_form:
                logging.error("Login form not found on the login page.")
                return False

            # Extract all form inputs and buttons
            form_elements = login_form.find_all(["input", "button"])
            form_data_list = []
            for elem in form_elements:
                name = elem.get("name")
                value = elem.get("value", "")
                if name:
                    form_data_list.append((name, value))

            logging.debug(f"Extracted form fields: {form_data_list}")

            # Update username and password in form data
            # Remove existing 'username' and 'password' entries
            form_data_list = [
                (name, value)
                for (name, value) in form_data_list
                if name not in ["username", "password"]
            ]
            form_data_list.append(("username", self.username))
            form_data_list.append(("password", self.password))

            # Log the form data being sent, excluding the password
            form_data_sanitized = [
                (name, "******" if name == "password" else value)
                for (name, value) in form_data_list
            ]
            logging.debug(
                f"Form data to be sent in POST request: {form_data_sanitized}"
            )

            # Use the login URL as the Referer for the POST request
            post_headers = headers.copy()
            post_headers["Referer"] = login_url
            post_headers["Origin"] = self.base_url

            # Step 3: POST to the login URL, allow redirects
            async with session.post(
                login_url,
                data=form_data_list,
                headers=post_headers,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                post_login_html = await response.text()
                logging.debug(
                    f"Received response from login POST with status {response.status}"
                )
                logging.debug(f"Response headers: {response.headers}")
                logging.debug(
                    f"Session cookies after POST: {session.cookie_jar.filter_cookies(login_url)}"
                )

            # Save the post-login page HTML for debugging
            with open("post_login_page.html", "w", encoding="utf-8") as f:
                f.write(post_login_html)

                # Step 4: Verify login is successful
                if (
                    self.logout in post_login_html
                    or "Wyloguj" in post_login_html
                    or "Log out" in post_login_html
                ):
                    logging.info("Login successful.")
                    return True
                else:
                    # Raise an exception to trigger the retry
                    error_message = soup.find("div", class_="error")
                    if error_message:
                        msg = f"Login failed: {error_message.text.strip()}"
                    else:
                        msg = "Login failed. No error message found."
                    logging.error(msg)
                    raise Exception(msg)

        except Exception as e:
            logging.exception(f"Exception during login: {e}")
            raise  # Re-raise the exception to trigger retry

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
                group_url: str = f"{self.base_url}{self.group_url}{group_id}&start={start}"
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

    async def run(self) -> None:
        """
        Run the scraper to login and fetch group members.

        Returns:
            None
        """
        connector = aiohttp_socks.ProxyConnector.from_url(TOR_PROXY_URL)
        async with aiohttp.ClientSession(connector=connector) as session:
            logged_in: bool = await self.login(session)
            if logged_in:
                await self.get_group_members(session, group_id=self.group_id)
                # Process the members list as needed
                for username, profile_url in self.members:
                    print(f"User: {username}, Profile URL: {profile_url}")
            else:
                print("Login failed.")


# Entry point
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    username: str = FORUM_USERNAME
    password: str = FORUM_PASSWORD

    scraper: LoggedInForumScraper = LoggedInForumScraper(username, password)
    asyncio.run(scraper.run())
