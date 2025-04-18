# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build/Run Commands
- Install dependencies: `pip install -r requirements.txt`
- Setup database: `alembic upgrade head`
- Run application: `python run.py`
- Run Celery worker: `celery -A celery_worker worker --loglevel=info`
- Run tests: `pytest tests/`
- Run single test: `pytest tests/test_file.py::test_function_name -v`
- Debug tests: `pytest tests/test_file.py -v --pdb`
- Run with coverage: `pytest --cov=app tests/`
- Build with Docker: `docker-compose up -d --build`
- Lint code: `flake8 app/ tests/`

## Code Style Guidelines
- 4-space indentation, no tabs
- 100 character line length max
- Import order: standard library → third-party → local application 
- Docstrings for API routes and core functions
- Class naming: CamelCase
- Function/variable naming: snake_case
- Explicit error handling with try/except blocks
- Use type hints for function parameters and return values
- Prefer explicit over implicit
- Use f-strings for string formatting
- Follow RESTful API patterns in route definitions
- Mock database sessions in tests using pytest fixtures
- Group imports by type with a blank line between groups
- Log exceptions with detailed context