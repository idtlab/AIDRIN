.. _adroit_integration:

ADROIT
=======

**ADROIT** (Agentic Data Readiness via Orchestrated Intelligent Toolkit) is an LLM-powered data
readiness agent bundled with AIDRIN. While AIDRIN provides
quantitative, metric-driven evaluation of dataset quality, ADROIT adds a *question-answering data
readiness evaluation and remediation* layer: given domain-specific literature (papers, regulatory documents, standards),
ADROIT automatically answers data readiness questions against an actual dataset and generates
actionable, domain-grounded remediation recommendations.

ADROIT is provided as a separate optional extra (``aidrin[adroit]``) because it requires LLM API
access and heavier dependencies not needed for standard AIDRIN use.

----

How ADROIT Works
----------------

ADROIT runs a five-stage pipeline for each data readiness question:

1. **Data Profiler** — loads the dataset and computes compact summary statistics (counts, means,
   missing ratios, top categories) to give the LLM structural context about the data.

2. **Vector Retriever** — searches a pre-built FAISS vector index of domain literature (PDFs, text
   files) to retrieve the most relevant passages for each question. If retrieval is disabled, the LLM
   answers from its own knowledge and the dataset profile alone.

3. **Code Executor** — uses the retrieved context and profile to prompt an LLM to write executable
   Python/pandas code, then runs that code directly against the dataset. A self-healing loop
   automatically repairs failing code, up to a configurable number of attempts.

4. **Complexity Scorer** — scores each query on three dimensions (profile dependency, domain
   knowledge dependency, code complexity) to classify queries as ``easy``, ``moderate``, or ``hard``.

5. **Remediation Generator** — synthesises concrete, domain-grounded remediation recommendations
   for each finding, citing the same domain literature used during retrieval.

Multiple questions can be processed in parallel via a configurable thread pool
(``retrieval.max_workers``). All results are written to a timestamped JSON log.

----

Installation
------------

**From source (development)**

.. code-block:: bash

   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN
   conda create -n aidrin-adroit-env python=3.10 -y
   conda activate aidrin-adroit-env
   pip install -e ".[adroit]"

.. note::

   For Google Gemini embedding models, additionally install ``langchain-google-genai``:

   .. code-block:: bash

      pip install langchain-google-genai

----

Worked Example: UCI Power Consumption Dataset
---------------------------------------------

This end-to-end example walks through using ADROIT on the
`UCI Individual Household Electric Power Consumption <https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption>`_
dataset — a real-world time-series dataset of ~2 million minute-level household energy readings
with known data quality challenges including ~1.25% missing values.

The metadata, domain literature PDFs, and config are already bundled with the package.
The only file you need to supply is the dataset itself.

Step 1: Set your API key
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

Step 2: Download and place the dataset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Download ``household_power_consumption.zip`` from:

   https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

Extract and place ``household_power_consumption.txt`` in the following location
(all paths relative to the AIDRIN root):

.. code-block:: text

   aidrin/adroit/
   ├── configs/
   │   └── power_consumption.yaml              ← bundled
   └── use_cases/
       └── power_consumption/
           ├── data/
           │   ├── metadata.txt                ← bundled
           │   └── household_power_consumption.txt  ← add this
           └── sources/
               └── *.pdf                       ← bundled

Step 3: Build the vector store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run from the AIDRIN root (once):

.. code-block:: bash

   python -m aidrin.adroit.vector_db_builder -c aidrin/adroit/configs/power_consumption.yaml

Step 4: Run the pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   python -m aidrin.adroit.run -c aidrin/adroit/configs/power_consumption.yaml -o aidrin/adroit/results/power_consumption.json

Output will be written to the specified JSON file and also printed to stdout.


Using ADROIT with Your Own Dataset
------------------------------------

Follow the same four steps as the example above, substituting your own dataset and literature.

Step 1: Set your API key
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   export OPENAI_API_KEY="sk-..."

Step 2: Prepare your dataset and domain literature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create the following layout under the AIDRIN root:

.. code-block:: text

   aidrin/adroit/use_cases/
   └── my_dataset/
       ├── data/
       │   ├── my_data.csv       # the dataset
       │   └── metadata.csv      # column-level metadata (CSV or plain text)
       └── sources/              # domain literature to index (PDF, TXT)
           ├── reference.pdf
           └── standards.txt

Step 3: Write a YAML config
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   # aidrin/adroit/configs/my_dataset.yaml

   paths:
     data_csv: "./use_cases/my_dataset/data/my_data.csv"
     metadata_csv: "./use_cases/my_dataset/data/metadata.csv"

   profiling:
     full_summary: false

   vector_store:
     sources:
       - ./use_cases/my_dataset/sources
     embedding_model: text-embedding-3-large
     chunk_size: 1000
     chunk_overlap: 200
     vector_store_name: my_dataset_vector_store

   retrieval:
     enabled: true
     max_workers: 8
     answer_model: gpt-5.2
     top_k: 3
     question:
       - "Does the age feature satisfy the HIPAA Safe Harbor de-identification standard?"

   executor:
     enabled: true
     max_attempts: 5
     model: gpt-5.2
     temperature: 0.0

   complexity_scorer:
     enabled: true
     model: gpt-5.2

   remediation:
     enabled: true
     model: gpt-5.2
     context_chars: 3000

Step 4: Build the vector store and run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run from the AIDRIN root:

.. code-block:: bash

   python -m aidrin.adroit.vector_db_builder -c aidrin/adroit/configs/my_dataset.yaml
   python -m aidrin.adroit.run -c aidrin/adroit/configs/my_dataset.yaml -o aidrin/adroit/results/output.json

Options:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Flag
     - Description
   * - ``-c`` / ``--config``
     - Path to YAML config (required)
   * - ``-o`` / ``--output``
     - Path to write JSON results (optional; also printed to stdout)

----

Custom Data Loaders
-------------------

For datasets that require custom loading logic (multiple files, Parquet, HDF5, etc.), write a
Python function that returns a ``pandas.DataFrame`` and reference it in the YAML config:

.. code-block:: python

   # my_project/loaders.py
   import pandas as pd
   from pathlib import Path

   def load_dataset() -> pd.DataFrame:
       return pd.read_parquet(Path("use_cases/my_dataset/data/my_data.parquet"))

.. code-block:: yaml

   paths:
     data_loader: "my_project.loaders:load_dataset"
     metadata_csv: "./use_cases/my_dataset/data/metadata.csv"

The built-in loader for the power consumption example is available at:

.. code-block:: text

   aidrin.adroit.dataloaders.power_consumption:load_dataset

----
