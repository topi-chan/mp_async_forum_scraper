docker build -t tor-selenium-scraper .
docker run -it -v "$(pwd)":/app tor-selenium-scraper /bin/bash
docker run -it -v "$(pwd)":/app tor-selenium-scraper python scrape.py

docker build -t scraper-api .
docker run -it -p 8000:8000 -v "$(pwd)":/app --name scraper-container scraper-api /bin/bash
uvicorn main:app --host 0.0.0.0 --port 8000

docker-compose up -d --build
docker-compose exec scraper-api /bin/bash

create torrc file
docker-compose -f docker-compose.prod.yml up -d
docker-compose ps
docker-compose exec tor cat <HiddenServiceDir/hostname>
