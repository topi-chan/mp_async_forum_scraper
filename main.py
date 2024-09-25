import logging
import os
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psutil
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates

from auth import (ACCESS_TOKEN_EXPIRE_MINUTES, authenticate_user,
                  create_access_token, get_current_active_user,
                  get_current_user, get_password_hash, users_collection,
                  verify_password)
from config import ARCHIVE_FILENAME, PID_FILE, RESULTS_DIR
from models import PasswordChangeRequest, User
from setup import setup_api_logging

setup_api_logging()

app = FastAPI()

# Set up Jinja2 templates and datetime format filter for Warsaw timezone
def datetimeformat(value, format="%Y-%m-%d %H:%M:%S"):
    dt = datetime.fromtimestamp(value, tz=ZoneInfo("Europe/Warsaw"))
    return dt.strftime(format)

templates = Jinja2Templates(directory="templates")
templates.env.filters["datetimeformat"] = datetimeformat


@app.get("/")
def read_root():
    logging.info("Root endpoint accessed.")
    # Redirect to the status page
    return RedirectResponse(url="/status", status_code=303)


@app.get("/status")
async def check_status(
    request: Request, current_user: User = Depends(get_current_active_user)
):
    """
    Endpoint that shows the scraping status.
    """
    archive_path = os.path.join(RESULTS_DIR, ARCHIVE_FILENAME)
    pid_file = PID_FILE

    is_running = False
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid = int(f.read())
        if psutil.pid_exists(pid):
            is_running = True
        else:
            # Remove stale PID file
            os.remove(pid_file)

    if is_running:
        status = "in_progress"
    elif os.path.isfile(archive_path):
        status = "complete"
    else:
        status = "not_started"

    # Get last modified time
    last_modified = (
        os.path.getmtime(archive_path) if os.path.isfile(archive_path) else None
    )

    # Get the user who started the scraping (if running)
    scraper_username = None
    if is_running:
        if os.path.exists("scraper_user.txt"):
            with open("scraper_user.txt", "r") as f:
                scraper_username = f.read().strip()

    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "status": status,
            "last_modified": last_modified,
            "scraper_username": scraper_username,
            "current_user": current_user,
        },
    )


@app.post("/scrape")
async def scrape_and_redirect(current_user: User = Depends(get_current_active_user)):
    """
    Endpoint that starts the scraping process and redirects to a status page.
    """
    pid_file = PID_FILE

    # Check if the scraper is already running
    is_running = False
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            pid = int(f.read())
        if psutil.pid_exists(pid):
            is_running = True
        else:
            # Remove stale PID file
            os.remove(pid_file)

    # Rate limiting for non-admin users
    if not current_user.is_admin:
        if current_user.last_scrape_time:
            time_since_last_scrape = datetime.utcnow() - current_user.last_scrape_time
            if time_since_last_scrape < timedelta(hours=1):
                remaining_time = timedelta(hours=1) - time_since_last_scrape
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
        script_path = os.path.abspath("scrape.py")
        process = subprocess.Popen(["python", script_path])

        # Write the subprocess's PID to the PID file
        with open(pid_file, "w") as f:
            f.write(str(process.pid))

        logging.info(f"Scraper process started with PID {process.pid}.")

        # Save the username of the user who started the scraper
        with open("scraper_user.txt", "w") as f:
            f.write(current_user.username)

        # Update user's last_scrape_time
        await users_collection.update_one(
            {"username": current_user.username},
            {"$set": {"last_scrape_time": datetime.utcnow()}},
        )

        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)


@app.get("/scrape")
async def redirect_to_status():
    return RedirectResponse(url="/status", status_code=303)


@app.get("/download")
async def download_file(current_user: User = Depends(get_current_active_user)):
    """
    Endpoint to download the scraped archive. Requires authentication.
    """
    archive_path = os.path.join(RESULTS_DIR, ARCHIVE_FILENAME)
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
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )
    response_data = {"access_token": access_token, "token_type": "bearer"}

    if user.password_needs_reset:
        response_data["password_needs_reset"] = True  # Inform client

    return response_data


@app.post("/change-password")
async def change_password(
    password_change: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
):
    # Verify the current password
    if not await verify_password(
        password_change.current_password, current_user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # Update the password
    hashed_password = await get_password_hash(password_change.new_password)
    await users_collection.update_one(
        {"username": current_user.username},
        {"$set": {"hashed_password": hashed_password, "password_needs_reset": False}},
    )
    return {"detail": "Password changed successfully"}
