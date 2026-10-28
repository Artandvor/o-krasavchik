.PHONY: up down logs seed test
up:      ## собрать и запустить → http://localhost:8080
	docker compose up --build -d && echo "→ http://localhost:8080"
down:
	docker compose down
logs:
	docker compose logs -f app
seed:    ## пересобрать демо-данные из OSM / Copernicus / Open-Meteo (~15 мин, нужен интернет)
	docker compose --profile pipeline run --rm pipeline
test:
	docker compose --profile pipeline run --rm pipeline python -m pytest -q
