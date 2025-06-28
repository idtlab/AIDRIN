<p align='center'>
    <img src="aidrin/images/logo.png" alt="Preview" alt="AIDRIN logo" style="width: 40%; height: auto; align: center"/>
</p>

# AIDRIN - AI Data Readiness Inspector


**AIDRIN** is a tool developed to assess the readiness of datasets for artificial intelligence applications. It helps users quickly evaluate the quality, structure, and completeness of their data to ensure it meets the foundational requirements for machine learning and other AI workflows.

---

## Features

- Evaluate dataset readiness for AI applications
- Web-based interface for interactive analysis
- Lightweight and easy to install
- Open-source and customizable

---

## Installation (Using Conda)

### 1. Clone the Repository

```bash
git clone https://github.com/idtlab/AIDRIN.git
cd AIDRIN
```

### 2. Create and Activate the Conda Environment

```bash
conda create -n aidrin-env python==3.10 -y
conda activate aidrin-env
pip install -e .
```

## Running the App

To start the development server:

```bash
flask --app aidrin run --debug
```

After the server starts, open your browser and navigate to: http://127.0.0.1:5000

## Citation
If you use AIDRIN in your research or publication, please cite as:

```
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
