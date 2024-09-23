docker build -t tor-selenium-scraper .

docker run -it -v "$(pwd)":/app tor-selenium-scraper /bin/bash

docker run -it -v "$(pwd)":/app tor-selenium-scraper python scrape.py

