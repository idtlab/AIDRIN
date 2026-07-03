.. _cli:
.. _cli_installation:

CLI Installation
================

AIDRIN includes a full-featured command line interface (CLI) that lets you run data readiness
metrics directly from your terminal — no web server or browser required. This is suitable for
scripted pipelines, CI workflows, and automated data quality checks.

For web application installation, see the :ref:`web_installation` page.

----

Option 1: Install from Source
------------------------------

Use this if you want the latest development version or plan to contribute:

.. code-block:: bash

   git clone https://github.com/idtlab/AIDRIN.git
   cd AIDRIN
   conda create -n aidrin-env python=3.10 -y
   conda activate aidrin-env
   pip install -e .

Once installed, the ``aidrin`` command is available system-wide:

.. code-block:: bash

   aidrin --help

----

Option 2: Install from PyPI
----------------------------

The simplest way to get the CLI:

.. code-block:: bash

   pip install aidrin

----

Agentic Evaluation (Optional)
------------------------------

The **agentic evaluation** component is AIDRIN's domain-aware data readiness evaluation extension.
It uses LLMs and retrieval-augmented generation over domain literature to answer dataset-specific
readiness questions. It requires additional dependencies — install it as a separate optional extra:

.. code-block:: bash

   # PyPI install
   pip install "aidrin[agentic]"

   # Source install
   pip install -e ".[agentic]"

.. note::

   For Google Gemini embedding models, additionally install ``langchain-google-genai``:

   .. code-block:: bash

      pip install langchain-google-genai
