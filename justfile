# list available commands
default:
    @just --list


# deploy the project
deploy:
	git push dokku main

# configure the local dev env
dev-config:
	cp dotenv-sample .env
	./scripts/dev-env.sh .env

# set up/update the local dev env
setup:
    pip install -r requirements.txt
    pre-commit install

# run the dev server
run:
    python manage.py runserver

# run the test suite and coverage
test:
	pytest --cov=nhs_openid_connect --cov=gateway --cov=tests

# run specific test(s)
test-only TESTPATH:
    pytest {{TESTPATH}}

# run the format checker, sort checker and linter
check:
    #!/bin/bash
    set -e
    echo "Running black, isort and flake8"
    black --check .
    isort --check-only --diff .
    flake8

# run the format checker (black)
format:
    #!/bin/bash
    set -e
    echo "Running black"
    black --check .

# run the linter (flake8)
lint:
    #!/bin/bash
    set -e
    echo "Running flake8"
    flake8

# run the sort checker (isort)
sort:
    #!/bin/bash
    set -e
    echo "Running isort"
    isort --check-only --diff .

# fix formatting and import sort ordering
fix:
    black .
    isort .