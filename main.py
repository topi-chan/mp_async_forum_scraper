import io
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import psutil
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
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
from services import (activities_collection, fetch_active_mods,
                      fetch_activities_from_db, get_missing_date_ranges,
                      save_activities_from_csv_to_db)
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
    last_modified: Optional[float] = (
        os.path.getmtime(archive_path) if os.path.isfile(archive_path) else None
    )

    # Get the user who started the scraping (if running)
    scraper_username: Optional[str] = None
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
    logged_last_modified: Optional[float] = None

    # Determine the status of logged_scrape.py
    if logged_is_running:
        logged_status = "in_progress"
    else:
        # Check if activities data exists in the database
        data_exists = await check_activities_data_exists()
        if data_exists:
            logged_status = "complete"
            # Get the last modified time from the latest activity
            latest_activity = await activities_collection.find_one(sort=[("date", -1)])
            if latest_activity:
                logged_last_modified = latest_activity["date"].timestamp()
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
    logging.debug(f"Data exists in DB: {data_exists}")
    logging.debug(f"logged_status set to: {logged_status}")

    # Pass any messages from the query parameters
    message = request.query_params.get("message")

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
            "message": message,
        },
    )


async def check_activities_data_exists() -> bool:
    """
    Check if there are any activities data in the database.
    """
    count = await activities_collection.count_documents({})
    return count > 0


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
    mods_scope: str = Form(...),
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> RedirectResponse:
    """
    Endpoint that starts the mods activity scraping process after checking for existing data.
    """
    # Validate dates
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        end_date_obj = end_date_obj.replace(
            hour=23, minute=59, second=59
        )  # Include entire end date
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Please use YYYY-MM-DD."
        )

    if start_date_obj > end_date_obj:
        raise HTTPException(
            status_code=400, detail="Start date must be before end date."
        )

    # Check for existing data
    missing_date_ranges = await get_missing_date_ranges(start_date_obj, end_date_obj)

    if not missing_date_ranges:
        # All data already scraped
        logging.info("All requested data is already available in the database.")
        # Redirect to status page with a message
        return RedirectResponse(
            url="/status?message=Data%20already%20available", status_code=303
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
        # Start the scraper for each missing date range
        for range_start, range_end in missing_date_ranges:
            # Convert datetime objects to strings
            range_start_str = range_start.strftime("%Y-%m-%d")
            range_end_str = range_end.strftime("%Y-%m-%d")
            # Start the logged scraper as a subprocess with date arguments and mods_scope
            script_path: str = os.path.abspath("logged_scrape.py")
            process_args = [
                sys.executable,
                script_path,
                "--start_date",
                range_start_str,
                "--end_date",
                range_end_str,
                "--mods_scope",
                mods_scope,  # Pass the mods_scope argument
            ]
            process = subprocess.Popen(process_args)
            logging.info(
                f"Mods activity scraper started for range {range_start_str} to {range_end_str} with PID {process.pid}."
            )

            # Write the subprocess PID to the PID file
            with open(LOGGED_PID_FILE, "w") as f:
                f.write(str(process.pid))

            # Save the username of the user who started the scraper
            with open("mods_scraper_user.txt", "w") as f:
                f.write(current_user.username)

            # Wait for the scraper to finish before starting the next one
            process.wait()

            # After scraper finishes, save activities to the database
            await save_activities_from_csv_to_db(LOGGED_OUTPUT_FILE, mods_scope)

            # Clean up the activities.csv file if needed
            if os.path.exists(LOGGED_OUTPUT_FILE):
                os.remove(LOGGED_OUTPUT_FILE)

            # Remove the PID file after completion
            if os.path.exists(LOGGED_PID_FILE):
                os.remove(LOGGED_PID_FILE)

            # Remove the scraper user file
            if os.path.exists("mods_scraper_user.txt"):
                os.remove("mods_scraper_user.txt")

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
    start_date: str,
    end_date: str,
    mods_scope: str = "active",
    current_user: User = Depends(get_current_active_user_from_cookie),
) -> StreamingResponse:
    """
    Endpoint to download the mods activity CSV from the database.
    """
    # Convert start_date and end_date to datetime objects
    try:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        end_date_obj = end_date_obj.replace(hour=23, minute=59, second=59)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Please use YYYY-MM-DD."
        )

    # Fetch activities from the database
    activities = await fetch_activities_from_db(start_date_obj, end_date_obj)

    if not activities:
        raise HTTPException(
            status_code=404, detail="No activities found for the specified date range."
        )

    # If mods_scope is 'active', filter activities for active mods
    if mods_scope == "active":
        active_mods = await fetch_active_mods()
        activities = [
            activity for activity in activities if activity.moderator in active_mods
        ]

    if not activities:
        raise HTTPException(
            status_code=404, detail="No activities found for the specified criteria."
        )

    # Convert activities to DataFrame
    df = pd.DataFrame([activity.dict() for activity in activities])

    # Generate CSV data
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    response = StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=activities.csv"},
    )
    return response
