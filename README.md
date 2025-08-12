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

To shut down AIDRIN and release system resources, follow the steps below in order:

### 1. Stop the Flask Application (Terminal 3)
Press `Ctrl+C` in the terminal running the Flask application.

### 2. Stop the Celery Worker (Terminal 2)
Press `Ctrl+C` in the terminal running the Celery worker. Wait a few seconds for a graceful shutdown.

### 3. Stop the Redis Server (Terminal 1)

If you started Redis manually:

```bash
redis-cli shutdown
```

If Redis is running as a system service (e.g., on Ubuntu):

```bash
sudo systemctl stop redis
```

### 4. Verify All Processes Are Terminated
Check for any remaining processes:

```bash
pgrep -f redis
pgrep -f celery
pgrep -f flask
```

If any remain, terminate them manually:

```bash
kill -9 <PID>
```

Replace `<PID>` with the actual process ID.
Alternatively, to check for used ports (6379 for Redis, 5000 for Flask):

```bash
lsof -i :6379
lsof -i :5000
```
