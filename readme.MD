docker build -t tor-selenium-scraper .
docker run -it -v "$(pwd)":/app tor-selenium-scraper /bin/bash
docker run -it -v "$(pwd)":/app tor-selenium-scraper python scrape.py

docker build -t scraper-api .
docker run -it -p 8000:8000 -v "$(pwd)":/app --name scraper-container scraper-api /bin/bash
uvicorn main:app --host 0.0.0.0 --port 8000

docker-compose up --build
docker-compose down
docker-compose exec scraper-api /bin/bash

create torrc file
docker-compose -f docker-compose.prod.yml up --build (--no-cache if needed -d if needed or just --build)
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml down
docker-compose ps
docker-compose exec tor bash
cat <HiddenServiceDir/hostname>
docker-compose exec scraper-api /bin/bash
docker-compose -f docker-compose.prod.yml logs -f scraper-api
