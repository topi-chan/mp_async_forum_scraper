import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psutil
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import (BaseHTTPMiddleware,
                                       RequestResponseEndpoint)

from auth import (ACCESS_TOKEN_EXPIRE_MINUTES, authenticate_user,
                  create_access_token, get_current_active_user_from_cookie,
                  get_current_user, get_password_hash, users_collection,
                  verify_password)
from config import ARCHIVE_FILENAME, PID_FILE, RESULTS_DIR
from models import User
from setup import setup_api_logging

setup_api_logging()

app = FastAPI()


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle authentication by checking for an access token in cookies.

    If the request URL is not for login or token endpoints and the access token is missing,
    the user is redirected to the login page.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Process the incoming request and check for authentication.

        :param request: The incoming request object.
        :param call_next: The next request handler in the middleware chain.
        :return: A RedirectResponse to the login page if the access token is missing,
                 otherwise the response from the next request handler.
        """
        if request.url.path not in ["/login", "/token"] and not request.cookies.get(
            "access_token"
        ):
            return RedirectResponse(url="/login")
        response = await call_next(request)
        return response


app.add_middleware(AuthMiddleware)


def datetimeformat(value: float, format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format a timestamp into a datetime string in the Europe/Warsaw timezone.

    :param value: The timestamp to format.
    :param format: The format string.
    :return: The formatted datetime string.
    """
    dt = datetime.fromtimestamp(value, tz=ZoneInfo("Europe/Warsaw"))
    return dt.strftime(format)


templates = Jinja2Templates(directory="templates")
templates.env.filters["datetimeformat"] = datetimeformat


@app.get("/")
def read_root() -> RedirectResponse:
    """
    Root endpoint that redirects to the login page.

    :return: A RedirectResponse to the login page.
    """
    logging.info("Root endpoint accessed.")
    return RedirectResponse(url="/login")


@app.get("/login")
def login_page(request: Request) -> Jinja2Templates.TemplateResponse:
    """
    Render the login page.

    :param request: The request object.
    :return: The login page template response.
    """
    return templates.TemplateResponse("login.html", {"request": request})


LOGGED_PID_FILE = "logged_scrape.pid"
LOGGED_OUTPUT_FILE = os.path.join(
    RESULTS_DIR, "activities.csv"
)  # Adjust path if necessary


@app.get("/status")
async def check_status(
    request: Request, current_user: User = Depends(get_current_active_user_from_cookie)
) -> Jinja2Templates.TemplateResponse:
    """
    Endpoint that shows the scraping status.

    :param request: The request object.
    :param current_user: The current authenticated user.
    :return: The status page template response or form to change password.
    """
    # Check if the user needs to reset their password
    if current_user.password_needs_reset:
        return RedirectResponse(url="/reset-password", status_code=303)

    # --- Check status of scrape.py ---
    archive_path: str = os.path.join(RESULTS_DIR, ARCHIVE_FILENAME)
    pid_file: str = PID_FILE

    is_running: bool = False
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid: int = int(f.read())
        if psutil.pid_exists(pid):
            is_running = True
        else:
            # Remove stale PID file
            os.remove(pid_file)

    if is_running:
        status: str = "in_progress"
    elif os.path.isfile(archive_path):
        status = "complete"
    else:
        status = "not_started"

    # Get last modified time for scrape.py output
    last_modified: float | None = (
        os.path.getmtime(archive_path) if os.path.isfile(archive_path) else None
    )

    # Get the user who started the scraping (if running)
    scraper_username: str | None = None
    if is_running:
        if os.path.exists("scraper_user.txt"):
            with open("scraper_user.txt", "r") as f:
                scraper_username = f.read().strip()

    # --- Check status of logged_scrape.py ---
    logged_is_running: bool = False
    if os.path.exists(LOGGED_PID_FILE):
        with open(LOGGED_PID_FILE, "r") as f:
            logged_pid: int = int(f.read())
        if psutil.pid_exists(logged_pid):
            logged_is_running = True
        else:
            # Remove stale PID file
            os.remove(LOGGED_PID_FILE)

    # Initialize logged_status and logged_last_modified
    logged_last_modified = None

    # Determine the status of logged_scrape.py
    if logged_is_running:
        logged_status = "in_progress"
    elif os.path.isfile(LOGGED_OUTPUT_FILE):
        logged_status = "complete"
        # Get last modified time
        logged_last_modified = os.path.getmtime(LOGGED_OUTPUT_FILE)
    else:
        logged_status = "not_started"

    # Get the user who started the mods activity scraping (if running)
    mods_scraper_username: Optional[str] = None
    if logged_is_running:
        if os.path.exists("mods_scraper_user.txt"):
            with open("mods_scraper_user.txt", "r") as f:
                mods_scraper_username = f.read().strip()

    # Log the logged_status for debugging
    logging.debug(f"logged_is_running: {logged_is_running}")
    logging.debug(f"LOGGED_OUTPUT_FILE exists: {os.path.isfile(LOGGED_OUTPUT_FILE)}")
    logging.debug(f"logged_status set to: {logged_status}")

    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "status": status,
            "last_modified": last_modified,
            "scraper_username": scraper_username,
            "current_user": current_user,
            "datetime": datetime,
            "timedelta": timedelta,
            "logged_status": logged_status,
            "logged_last_modified": logged_last_modified,
            "mods_scraper_username": mods_scraper_username,
        },
    )


@app.post("/scrape")
async def scrape_and_redirect(
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> RedirectResponse:
    """
    Endpoint that starts the scraping process and redirects to a status page.

    :param current_user: The current authenticated user.
    :return: A RedirectResponse to the status page.
    """
    pid_file: str = PID_FILE

    # Check if the scraper is already running
    is_running: bool = False
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid: int = int(f.read())
        if psutil.pid_exists(pid):
            is_running = True
        else:
            # Remove stale PID file
            os.remove(pid_file)

    # Rate limiting for non-admin users
    if not current_user.is_admin:
        if current_user.last_scrape_time:
            time_since_last_scrape: timedelta = (
                datetime.utcnow() - current_user.last_scrape_time
            )
            if time_since_last_scrape < timedelta(hours=1):
                remaining_time: timedelta = timedelta(hours=1) - time_since_last_scrape
                minutes, seconds = divmod(remaining_time.total_seconds(), 60)
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {int(minutes)} minutes and {int(seconds)} seconds before starting a new scrape.",
                )

    if is_running:
        logging.info("Scraper is already running.")
        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)
    else:
        # Start the scraper as a subprocess
        script_path: str = os.path.abspath("scrape.py")
        process = subprocess.Popen([sys.executable, script_path])

        # Write the subprocess PID to the PID file
        with open(pid_file, "w") as f:
            f.write(str(process.pid))

        logging.info(f"Scraper process started with PID {process.pid}.")

        # Save the username of the user who started the scraper
        with open("scraper_user.txt", "w") as f:
            f.write(current_user.username)

        # Update user's last_scrape_time
        current_user.last_scrape_time = datetime.utcnow()
        # Save the updated user data
        await users_collection.update_one(
            {"username": current_user.username},
            {"$set": {"last_scrape_time": current_user.last_scrape_time}},
        )

        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)


@app.post("/scrape_mods_activity")
async def scrape_mods_activity(
    start_date: str = Form(...),
    end_date: str = Form(...),
    mods_scope: str = Form(...),  # Added this line
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> RedirectResponse:
    """
    Endpoint that starts the mods activity scraping process and redirects to a status page.

    :param start_date: The start date for scraping (from form).
    :param end_date: The end date for scraping (from form).
    :param mods_scope: 'active' or 'all' to determine which mods to scrape.
    :param current_user: The current authenticated user.
    :return: A RedirectResponse to the status page.
    """
    # Validate dates
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Please use YYYY-MM-DD."
        )

    if start_date_obj > end_date_obj:
        raise HTTPException(
            status_code=400, detail="Start date must be before end date."
        )

    # Check if the logged scraper is already running
    logged_is_running: bool = False
    if os.path.exists(LOGGED_PID_FILE):
        with open(LOGGED_PID_FILE, "r") as f:
            logged_pid: int = int(f.read())
        if psutil.pid_exists(logged_pid):
            logged_is_running = True
        else:
            # Remove stale PID file
            os.remove(LOGGED_PID_FILE)

    # Rate limiting for non-admin users
    if not current_user.is_admin:
        if current_user.last_mods_scrape_time:
            time_since_last_scrape: timedelta = (
                datetime.utcnow() - current_user.last_mods_scrape_time
            )
            if time_since_last_scrape < timedelta(hours=1):
                remaining_time: timedelta = timedelta(hours=1) - time_since_last_scrape
                minutes, seconds = divmod(remaining_time.total_seconds(), 60)
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {int(minutes)} minutes and {int(seconds)} seconds before starting a new mods activity scrape.",
                )

    if logged_is_running:
        logging.info("Mods activity scraper is already running.")
        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)
    else:
        # Start the logged scraper as a subprocess with date arguments and mods_scope
        script_path: str = os.path.abspath("logged_scrape.py")
        process_args = [
            sys.executable,
            script_path,
            "--start_date",
            start_date,
            "--end_date",
            end_date,
            "--mods_scope",
            mods_scope,  # Pass the mods_scope argument
        ]
        process = subprocess.Popen(process_args)

        # Write the subprocess PID to the LOGGED_PID_FILE
        with open(LOGGED_PID_FILE, "w") as f:
            f.write(str(process.pid))

        logging.info(f"Mods activity scraper started with PID {process.pid}.")

        # Save the username of the user who started the mods activity scraper
        with open("mods_scraper_user.txt", "w") as f:
            f.write(current_user.username)

        # Update user's last_mods_scrape_time
        current_user.last_mods_scrape_time = datetime.utcnow()
        # Save the updated user data
        await users_collection.update_one(
            {"username": current_user.username},
            {"$set": {"last_mods_scrape_time": current_user.last_mods_scrape_time}},
        )

        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)


@app.get("/scrape")
async def redirect_to_status() -> RedirectResponse:
    """
    Redirect to the status page.

    :return: A RedirectResponse to the status page.
    """
    return RedirectResponse(url="/status", status_code=303)


@app.get("/download")
async def download_file(
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> FileResponse:
    """
    Endpoint to download the scraped archive. Requires authentication.

    :param current_user: The current authenticated user.
    :return: The file response for the scraped archive.
    :raises HTTPException: If the archive is not found.
    """
    archive_path: str = os.path.join(RESULTS_DIR, ARCHIVE_FILENAME)
    if os.path.isfile(archive_path):
        logging.info("Archive found. Preparing to send the file.")
        return FileResponse(
            path=archive_path, filename=ARCHIVE_FILENAME, media_type="application/x-tar"
        )
    else:
        logging.warning(
            "Archive not found. User attempted to download before scraping."
        )
        raise HTTPException(
            status_code=404, detail="Archive not found. Please run the scraper first."
        )


@app.post("/token")
async def login_for_access_token(
    response: Response, form_data: OAuth2PasswordRequestForm = Depends()
) -> dict[str, Any]:
    """
    Endpoint to log in and obtain an access token.

    :param response: The response object.
    :param form_data: The form data containing username and password.
    :return: A dictionary with a success message and optional password reset flag.
    :raises HTTPException: If the username or password is incorrect.
    """
    user: Optional[User] = await authenticate_user(
        form_data.username, form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token_expires: timedelta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token: str = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    # Set the JWT token in a cookie after successful login
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=None,
        samesite="lax",
        secure=False,  # Set to True if using HTTPS
    )

    response_data: dict[str, Any] = {"message": "Login successful"}

    # If the user needs to reset their password, inform the frontend
    if user.password_needs_reset:
        response_data["password_needs_reset"] = True

    return response_data


@app.get("/reset-password")
async def reset_password_page(request: Request) -> Jinja2Templates.TemplateResponse:
    """
    Endpoint to render the password reset page.

    :param request: The request object.
    :return: The password reset page template response.
    """
    return templates.TemplateResponse("reset_password.html", {"request": request})


@app.post("/reset-password")
async def reset_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    current_user: User = Depends(get_current_user),
) -> Jinja2Templates.TemplateResponse:
    """
    Endpoint to handle password reset.

    :param request: The request object.
    :param current_password: The current password of the user.
    :param new_password: The new password to set.
    :param current_user: The current authenticated user.
    :return: The password reset confirmation page template response.
    :raises HTTPException: If the current password is incorrect.
    """
    # Verify the current password
    if not await verify_password(current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # Update the password
    hashed_password: str = await get_password_hash(new_password)
    await users_collection.update_one(
        {"username": current_user.username},
        {"$set": {"hashed_password": hashed_password, "password_needs_reset": False}},
    )

    # Render confirmation page
    return templates.TemplateResponse(
        "password_reset_confirmation.html", {"request": request}
    )


@app.get("/logout")
async def logout() -> RedirectResponse:
    """
    Endpoint to log the user out by clearing the access_token cookie and showing a logout confirmation page.

    :return: The logout confirmation page template response.
    """
    # Ensure all attributes are properly matched when deleting the cookie
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key="access_token",
        path="/",
        domain=None,
        samesite="lax",
        secure=False,
        httponly=True,
    )
    return response


@app.get("/download_mods_activity")
async def download_mods_activity(
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> FileResponse:
    """
    Endpoint to download the mods activity CSV. Requires authentication.

    :param current_user: The current authenticated user.
    :return: The file response for the CSV file.
    :raises HTTPException: If the file is not found.
    """
    file_path: str = LOGGED_OUTPUT_FILE  # Use the same path as LOGGED_OUTPUT_FILE
    if os.path.isfile(file_path):
        logging.info("Mods activity summary found. Preparing to send the file.")
        return FileResponse(
            path=file_path, filename="activities.csv", media_type="text/csv"
        )
    else:
        logging.warning(
            "Mods activity summary not found. User attempted to download before scraping."
        )
        raise HTTPException(
            status_code=404,
            detail="Mods activity summary not found. Please run the scraper first.",
        )
