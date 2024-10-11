import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import aiohttp
import aiohttp_socks
import dateparser
import pandas as pd
import psutil
from bs4 import BeautifulSoup

from config import (ACTION_ELEMENT, ACTIVITY_CLASS, DATE_ELEMENT,
                    FORUM_PASSWORD, FORUM_USERNAME, GROUP_ID, GROUP_URL,
                    LOGIN_URL, LOGOUT_URL, LOGS_URL, MAIN_FORUM_URL,
                    MEMBERS_CLASS, MEMBERS_DIVS, RESULTS_DIR, TOR_PROXY_URL)
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
        self.logs_url: str = LOGS_URL
        self.activity_class: str = ACTIVITY_CLASS
        self.action_element: str = ACTION_ELEMENT
        self.date_element: str = DATE_ELEMENT
        self.activities: list[dict] = []
        self.headers = None
        self.activities_df = None

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

    def find_div_with_span_text(self, row, class_name, span_text):
        """
        Finds a <div> within the row where the <span> contains specific text.
        """
        divs = row.find_all("div", class_=class_name)
        for div in divs:
            span = div.find("span")
            if span and span.get_text(strip=True) == span_text:
                return div
        return None

    async def scrape_activity_logs(
        self, session: aiohttp.ClientSession, start_date: datetime, end_date: datetime
    ) -> None:
        """
        Scrape moderator activity logs within a date range.
        """
        try:
            page = 0
            self.headers = self.get_random_header()
            continue_scraping = True

            while continue_scraping:
                headers = self.headers
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
                    # Extract action and details
                    action_elem = row.find("div", class_=self.action_element)
                    if action_elem:
                        # Extract action type
                        action_type_elem = action_elem.find("strong")
                        if action_type_elem:
                            action_type_full = action_type_elem.text.strip()
                            # Extract base action by taking the first two words
                            base_action = " ".join(action_type_full.split()[:2])
                        else:
                            base_action = "Unknown"

                        # Extract details - text after the action type
                        details_parts = []
                        for content in action_elem.contents:
                            if content == action_type_elem:
                                continue  # Skip the action type element
                            if isinstance(content, str):
                                details_parts.append(content.strip())
                            else:
                                details_parts.append(
                                    content.get_text(separator=" ", strip=True)
                                )
                        details = " ".join(details_parts).strip()
                    else:
                        base_action = "Unknown"
                        details = ""

                    # Extract moderator name
                    mod_user_div = self.find_div_with_span_text(
                        row, self.date_element, "Opinie o użytkowniku:"
                    )
                    if mod_user_div:
                        mod_name_elem = mod_user_div.find(
                            "a", class_=self.members_class
                        )
                        if mod_name_elem:
                            moderator_name = mod_name_elem.text.strip()
                        else:
                            # If no 'a' element, extract text directly
                            moderator_name = (
                                mod_user_div.get_text(separator=" ", strip=True)
                                .replace("Opinie o użytkowniku:", "")
                                .strip()
                            )
                    else:
                        moderator_name = "Unknown"

                    # Extract date string
                    date_elem = self.find_div_with_span_text(
                        row, self.date_element, "Czas:"
                    )
                    if date_elem:
                        # Remove the span element to isolate the date text
                        span_elem = date_elem.find("span")
                        if span_elem:
                            span_elem.extract()
                        date_str = date_elem.get_text(strip=True)
                        if date_str:
                            # Parse the date string using dateparser
                            parsed_date = dateparser.parse(
                                date_str,
                                languages=["pl"],
                                settings={
                                    "TIMEZONE": "Europe/Warsaw",
                                    "RETURN_AS_TIMEZONE_AWARE": False,
                                },
                            )
                            if parsed_date is None:
                                logging.warning(f"Could not parse date: {date_str}")
                                continue  # Skip this activity if date parsing fails
                        else:
                            parsed_date = None
                            logging.warning("No date string found.")
                    else:
                        parsed_date = None
                        logging.warning("Date element not found.")

                    # Check if the activity is within the date range
                    if parsed_date:
                        if parsed_date < start_date:
                            # Older than start date; stop scraping
                            continue_scraping = False
                            break
                        elif parsed_date > end_date:
                            # Newer than end date; skip this activity
                            continue
                    else:
                        # If date is not parsed, skip this activity
                        continue

                    # Append to activities list
                    action_data = {
                        "Moderator": moderator_name,
                        "Action": base_action,
                        "Details": details,
                        "Date": parsed_date.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    self.activities.append(action_data)

                # Move to the next page
                page += 1

        except Exception as e:
            logging.error(f"Exception during scraping activity logs: {e}")

    async def run(
        self, start_date: datetime, end_date: datetime, mods_scope: str = "active"
    ) -> None:
        """
        Run the scraper to login and fetch group members and activities.

        Args:
            start_date (datetime): The start date for scraping activities.
            end_date (datetime): The end date for scraping activities.
            mods_scope (str): 'active' to include only active mods, 'all' to include all mods.

        Returns:
            None
        """
        connector = aiohttp_socks.ProxyConnector.from_url(TOR_PROXY_URL)
        async with aiohttp.ClientSession(connector=connector) as session:
            logged_in: bool = await self.login(session)
            if logged_in:
                # If mods_scope is 'active', fetch group members to get active moderators
                if mods_scope == "active":
                    # Fetch group members
                    await self.get_group_members(session, group_id=self.group_id)

                    # Create a set of active moderator names for quick lookup
                    active_moderators = set(
                        member[0].strip().lower() for member in self.members
                    )
                else:
                    active_moderators = None  # Won't filter by active moderators

                # Scrape moderator activities
                await self.scrape_activity_logs(session, start_date, end_date)

                # Process activities
                if self.activities:
                    self.activities_df = pd.DataFrame(self.activities)

                    if mods_scope == "active":
                        # Normalize moderator names in activities for matching
                        self.activities_df["Moderator_lower"] = (
                            self.activities_df["Moderator"].str.strip().str.lower()
                        )

                        # Filter activities to include only active moderators
                        filtered_activities_df = self.activities_df[
                            self.activities_df["Moderator_lower"].isin(
                                active_moderators
                            )
                        ].drop(columns=["Moderator_lower"])
                    else:
                        # Do not filter; include all moderators
                        filtered_activities_df = self.activities_df

                    if filtered_activities_df.empty:
                        logging.info("No activities found for selected moderators.")
                        print("No activities found for selected moderators.")
                        return

                    # Save detailed activities to CSV
                    filtered_activities_df.to_csv(
                        os.path.join(RESULTS_DIR, "activities.csv"),
                        index=False,
                        encoding="utf-8-sig",
                    )
                    logging.info("Detailed activities saved to 'activities.csv'.")

                    # Group actions by moderator and action type
                    summary = (
                        filtered_activities_df.groupby(["Moderator", "Action"])
                        .size()
                        .reset_index(name="Count")
                    )

                    # Save summary to CSV
                    summary.to_csv(
                        os.path.join(RESULTS_DIR, "activity_summary.csv"),
                        index=False,
                        encoding="utf-8-sig",
                    )
                    logging.info("Activity summary saved to 'activity_summary.csv'.")

                    # Optionally, print the summary
                    print(summary)
                else:
                    print("No activities found.")
            else:
                print("Login failed.")


LOGGED_PID_FILE = "logged_scrape.pid"
MODS_SCRAPER_USER_FILE = "mods_scraper_user.txt"


def parse_arguments():
    parser = argparse.ArgumentParser(description="Forum Scraper with date range")
    parser.add_argument("--start_date", help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end_date", help="End date in YYYY-MM-DD format")
    parser.add_argument(
        "--mods_scope",
        choices=["active", "all"],
        default="active",
        help="Specify whether to scrape activities of only active mods or all mods",
    )
    args = parser.parse_args()
    return args


def main():
    """
    Main function to execute the scraping process.

    Assumes that PID file handling has been done in the __main__ block.
    """

    # Parse command-line arguments
    args = parse_arguments()

    if args.start_date and args.end_date:
        # Use dates from command-line arguments
        try:
            # Convert the input strings to datetime objects
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
            # Add time component to end_date to include the entire day
            end_date = end_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            logging.error("Invalid date format. Please use YYYY-MM-DD.")
            sys.exit(1)
    else:
        # No command-line arguments provided; exit with error
        logging.error("Start date and end date must be provided as arguments.")
        sys.exit(1)

    try:
        logging.info(f"Starting logged scraping from {start_date} to {end_date}.")
        scraper = LoggedInForumScraper(username=FORUM_USERNAME, password=FORUM_PASSWORD)
        # Run the scraper asynchronously with the provided date range and mods_scope
        asyncio.run(scraper.run(start_date, end_date, mods_scope=args.mods_scope))
        logging.info("Logged scraping completed successfully.")

    except Exception as e:
        logging.error(f"An error occurred during logged scraping: {e}")

    # Remove the mods_scraper_user.txt file if it exists
    if os.path.exists(MODS_SCRAPER_USER_FILE):
        os.remove(MODS_SCRAPER_USER_FILE)
        logging.info("Mods scraper user file removed.")


if __name__ == "__main__":
    """
    Entry point of the script.

    Handles PID file management, configures logging, and starts the main scraping process.
    """
    pid_file = LOGGED_PID_FILE
    current_pid = os.getpid()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [PID: {current_pid}] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # PID file handling
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            existing_pid = int(f.read())

        if existing_pid == current_pid:
            # PID file contains our own PID; proceed
            logging.info(
                f"PID file exists and contains our PID {existing_pid}. Proceeding."
            )
        else:
            if psutil.pid_exists(existing_pid):
                logging.info(
                    f"PID file exists and process {existing_pid} is still running. Exiting."
                )
                sys.exit(1)
            else:
                # Stale PID file detected; remove it and proceed
                os.remove(pid_file)
                logging.info(f"Removed stale PID file with PID {existing_pid}.")
                # Write current PID to PID file
                with open(pid_file, "w") as f:
                    f.write(str(current_pid))
                logging.info(f"Logged scraper started with PID {current_pid}.")
    else:
        # PID file does not exist; create it
        with open(pid_file, "w") as f:
            f.write(str(current_pid))
        logging.info(f"Logged scraper started with PID {current_pid}.")

    start_time = time.perf_counter()
    try:
        main()
    finally:
        # Remove the PID file if it contains the current PID
        if os.path.exists(pid_file):
            with open(pid_file, "r") as f:
                pid_in_file = int(f.read())
            if pid_in_file == current_pid:
                os.remove(pid_file)
                logging.info("Logged scraper PID file removed.")
            else:
                logging.warning(
                    "PID file not removed because it contains a different PID."
                )
        else:
            logging.warning("PID file does not exist during cleanup.")

        end_time = time.perf_counter()
        total_time = end_time - start_time
        minutes, seconds = divmod(total_time, 60)
        logging.info(
            f"Logged scraping completed in {int(minutes)} minutes and {seconds:.2f} seconds."
        )
