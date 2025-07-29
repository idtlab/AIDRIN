# AIDRIN – AI Data Readiness Inspector

**AIDRIN** (AI Data Readiness Inspector) is a lightweight tool that helps users assess how ready their datasets are for AI and machine learning workflows. It provides an interactive web interface to evaluate the quality, completeness, and structure of datasets using quantitative metrics.

---

## Features

- Evaluate dataset readiness for AI applications  
- Interactive web interface for exploration  
- Lightweight, open-source, and customizable  
- Built with Flask, Celery, and Redis  

---

## Quickstart Guide

> Works on **macOS**, **Linux**, and **Windows** (via WSL or Anaconda)

---

## Prerequisites

- [Python 3.10](https://www.python.org/downloads/release/python-3100/)  
- [Conda (Anaconda or Miniconda)](https://docs.conda.io/en/latest/miniconda.html)   

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/idtlab/AIDRIN.git
cd AIDRIN
````

---

### 2. Create and Activate the Conda Environment

```bash
conda create -n aidrin-env python=3.10 -y
conda activate aidrin-env
python -m pip install -e .
```

---

## Required Services

AIDRIN uses **Redis** as a message broker for background task management, and **Celery** to run those tasks asynchronously.

### Install Redis Locally (No Docker Needed)

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

* Use [Windows Subsystem for Linux (WSL)](https://learn.microsoft.com/en-us/windows/wsl/install) and follow Linux instructions
* Or download and install Redis from [Microsoft’s archive](https://github.com/microsoftarchive/redis/releases)

Make sure Redis server is running on port 6379 (default).

---

## Starting the Application

You will need **three terminal windows/tabs** open:

---

### Terminal 1: Start Redis Server

Make sure Redis is running locally:

```bash
redis-server --port 6379
```

---

### Terminal 2: Start Celery Worker

From within the AIDRIN directory:

```bash
conda activate aidrin-env
PYTHONPATH=. celery -A aidrin.make_celery worker --loglevel=info
```

Wait until you see ``ready`` or ``waiting for tasks`` in the Celery logs. This may take 30 to 40 seconds.

---

### Terminal 3: Run Flask Application

From within the AIDRIN directory:

```bash
conda activate aidrin-env
flask --app aidrin run --debug
```

Open your browser and visit:
**[http://127.0.0.1:5000](http://127.0.0.1:5000)**


## Citation

If you use AIDRIN in your work, please cite:

```bibtex
@inproceedings{10.1145/3676288.3676296,
author = {Hiniduma, Kaveen and Byna, Suren and Bez, Jean Luca and Madduri, Ravi},
title = {AI Data Readiness Inspector (AIDRIN) for Quantitative Assessment of Data Readiness for AI},
year = {2024},
isbn = {9798400710209},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3676288.3676296},
doi = {10.1145/3676288.3676296},
booktitle = {Proceedings of the 36th International Conference on Scientific and Statistical Database Management},
articleno = {7},
numpages = {12},
keywords = {Data readiness for AI, Data readiness metrics, FAIR principles, data quality assessment},
location = {Rennes, France},
series = {SSDBM '24}
}
```