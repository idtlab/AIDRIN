# AIDRIN – AI Data Readiness Inspector

**AIDRIN** (AI Data Readiness Inspector) is a lightweight, open-source tool designed to evaluate the readiness of datasets for AI and machine learning workflows. It provides an intuitive web interface to assess dataset quality, completeness, and structure through quantitative metrics.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [For Users](#for-users)
- [For Contributors](#for-contributors)
- [Starting the Application](#starting-the-application)
- [License](#license)

## Features

- Assess dataset readiness for AI/ML applications
- Interactive web interface for seamless exploration
- Lightweight and customizable architecture
- Built with Flask, Celery, and Redis for robust performance

## Prerequisites

- [Python 3.10](https://www.python.org/downloads/release/python-3100/)
- [Conda (Anaconda or Miniconda)](https://docs.conda.io/en/latest/miniconda.html)
- [Redis](https://redis.io/docs/install/install-redis/) (for task queue management)
- Compatible with **macOS**, **Linux**, and **Windows** (via WSL or Anaconda)

## Installation

1. **Clone the Repository**

   ```bash
   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN
   ```

2. **Set Up Conda Environment**

   ```bash
   conda create -n aidrin-env python=3.10 -y
   conda activate aidrin-env
   python -m pip install -e .
   ```

## For Users

To use AIDRIN, complete the [Installation](#installation) steps and proceed to [Starting the Application](#starting-the-application).

## For Contributors

To contribute to AIDRIN, follow the [Installation](#installation) steps and set up pre-commit hooks to ensure code quality.

### Set Up Pre-Commit Hooks

AIDRIN uses [pre-commit](https://pre-commit.com/) to enforce code quality through automated checks before each commit. The hooks include:

- **Pyupgrade**: Enforces modern Python syntax (Python 3.8+)
- **Codespell**: Checks for common spelling mistakes
- **General Checks**: Validates YAML/JSON, fixes line endings, removes trailing whitespace, and prevents large file commits (>10MB)

Install and configure pre-commit:

```bash
pip install pre-commit
pre-commit install
```

This is a **one-time setup per clone**. To manually run all checks:

```bash
pre-commit run --all-files
```

## Starting the Application

AIDRIN requires **Redis** for task queuing and **Celery** for background task processing. You’ll need **three terminal windows/tabs** to run the application.

### Install Redis

#### On macOS (using Homebrew):

```bash
brew install redis
```

#### On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install redis-server
```

#### On Windows:

- Use [Windows Subsystem for Linux (WSL)](https://learn.microsoft.com/en-us/windows/wsl/install) and follow Linux instructions, or
- Install Redis from [Microsoft’s archive](https://github.com/microsoftarchive/redis/releases).

Ensure Redis is running on the default port (6379).

### Terminal 1: Start Redis Server

```bash
redis-server --port 6379
```

### Terminal 2: Start Celery Worker

```bash
conda activate aidrin-env
PYTHONPATH=. celery -A aidrin.make_celery worker --loglevel=info
```

Wait for the Celery logs to show `ready` or `waiting for tasks` (30–40 seconds).

### Terminal 3: Run Flask Application

```bash
conda activate aidrin-env
flask --app aidrin run --debug
```

Visit [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser to access AIDRIN.

## Stopping the Application

To properly shut down AIDRIN and free system resources:

1. **Stop Flask (Terminal 3)**: Press `Ctrl+C` in the terminal running the Flask application.
2. **Stop Celery (Terminal 2)**: Press `Ctrl+C` in the terminal running the Celery worker. Wait for a graceful shutdown (a few seconds).
3. **Stop Redis (Terminal 1)**: Press `Ctrl+C` in the terminal running the Redis server, or use:

   ```bash
   redis-cli shutdown
   ```

To verify all processes are terminated:

- Check for running processes:
  ```bash
  ps aux | grep redis
  ps aux | grep celery
  ps aux | grep flask
  ```
  If any processes persist, terminate them with `kill -9 <PID>` (replace `<PID>` with the process ID).

- Ensure ports 6379 (Redis) and 5000 (Flask) are free:
  ```bash
  netstat -an | grep 6379
  netstat -an | grep 5000
  ```

If Redis runs as a service (e.g., on Ubuntu), stop it with:

```bash
sudo systemctl stop redis
```
