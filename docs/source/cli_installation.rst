.. _cli:
.. _cli_installation:

CLI Installation
================

AIDRIN includes a full-featured command line interface (CLI) that lets you run data readiness
metrics directly from your terminal — no web server or browser required. This is suitable for
scripted pipelines, CI workflows, and automated data quality checks.

For web application installation, see the :ref:`web_installation` page.

----

Base CLI
--------

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

ADROIT (Optional)
-----------------

**ADROIT** is an LLM-powered extension that requires additional dependencies. Install it as a
separate optional extra:

.. code-block:: bash

   pip install -e ".[adroit]"

.. note::

   For Google Gemini embedding models, additionally install ``langchain-google-genai``:

   .. code-block:: bash

      pip install langchain-google-genai
