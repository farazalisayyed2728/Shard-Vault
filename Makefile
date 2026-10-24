.PHONY: up down migrate test lint

up:
	docker-compose up --build -d
	docker-compose exec web python manage.py migrate

down:
	docker-compose down

migrate:
	docker-compose exec web python manage.py makemigrations
	docker-compose exec web python manage.py migrate

test:
	docker-compose exec web pytest