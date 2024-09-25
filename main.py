import logging
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ARCHIVE_FILENAME, PID_FILE, RESULTS_DIR
from utils import setup_api_logging

setup_api_logging()

app = FastAPI()


def datetimeformat(value, format="%Y-%m-%d %H:%M:%S"):
    dt = datetime.fromtimestamp(value, tz=ZoneInfo("Europe/Warsaw"))
    return dt.strftime(format)


templates = Jinja2Templates(directory="templates")
# Register the custom filter
templates.env.filters["datetimeformat"] = datetimeformat


@app.get("/")
def read_root():
    logging.info("Root endpoint accessed.")
    return {
        "message": "Welcome to the Scraper API. Use /scrape to start scraping and /download to download the results."
    }


@app.get("/status")
async def check_status(request: Request):
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

    return templates.TemplateResponse(
        "status.html",
        {"request": request, "status": status, "last_modified": last_modified},
    )


# @app.get("/scrape")  # Remove in case need to restrict to POST requests only
@app.post("/scrape")
async def scrape_and_redirect():
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

        # Redirect to the status page
        return RedirectResponse(url="/status", status_code=303)


@app.get("/scrape")
async def redirect_to_status():
    return RedirectResponse(url="/status", status_code=303)


@app.get("/download")
async def download_file():
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


# backup endpoint
# @app.post("/scrape")
# @app.get("/scrape")  # Remove in case need to restrict to POST requests only
# async def trigger_scraping():
#     script_path = os.path.abspath("scrape.py")
#     # Start the scraper as a subprocess
#     subprocess.Popen(["python", script_path])
#     logging.info("Scraper process started.")
#     return {"message": "Scraping has been started."}
