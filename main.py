import logging
import os
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from config import ARCHIVE_NAME, RESULTS_DIR
from utils import setup_api_logging

setup_api_logging()

app = FastAPI()


templates = Jinja2Templates(directory="templates")


@app.get("/status")
async def check_status(request: Request):
    """
    Endpoint that shows the scraping status.
    """
    archive_path = os.path.join(RESULTS_DIR, ARCHIVE_NAME)
    if os.path.isfile(archive_path):
        # Scraping is complete
        status = "complete"
    else:
        # Scraping is still in progress
        status = "in_progress"

    return templates.TemplateResponse(
        "status.html", {"request": request, "status": status}
    )


@app.get("/scrape")  # Remove in case need to restrict to POST requests only
@app.post("/scrape")
async def scrape_and_redirect():
    """
    Endpoint that starts the scraping process and redirects to a status page.
    """
    # Start the scraper as a subprocess
    script_path = os.path.abspath("scrape.py")
    subprocess.Popen(["python", script_path])

    logging.info("Scraper process started.")

    # Redirect to the status page
    return RedirectResponse(url="/status", status_code=303)


@app.get("/download")
async def download_file():
    """
    Endpoint to download the scraped archive. Requires authentication.
    """
    archive_path = os.path.join(RESULTS_DIR, ARCHIVE_NAME)
    if os.path.isfile(archive_path):
        logging.info("Archive found. Preparing to send the file.")
        return FileResponse(
            path=archive_path, filename=ARCHIVE_NAME, media_type="application/x-tar"
        )
    else:
        logging.warning(
            "Archive not found. User attempted to download before scraping."
        )
        raise HTTPException(
            status_code=404, detail="Archive not found. Please run the scraper first."
        )


@app.get("/")
def read_root():
    logging.info("Root endpoint accessed.")
    return {
        "message": "Welcome to the Scraper API. Use /scrape to start scraping and /download to download the results."
    }


# backup endpoint
# @app.post("/scrape")
# @app.get("/scrape")  # Remove in case need to restrict to POST requests only
# async def trigger_scraping():
#     script_path = os.path.abspath("scrape.py")
#     # Start the scraper as a subprocess
#     subprocess.Popen(["python", script_path])
#     logging.info("Scraper process started.")
#     return {"message": "Scraping has been started."}
