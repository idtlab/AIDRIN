.. AIDRIN documentation master file

AIDRIN Documentation
====================

**AIDRIN** (AI Data Readiness Infrastructure) is an open-source tool designed to streamline the preparation and evaluation of datasets for artificial intelligence and machine learning workflows. AIDRIN enables researchers, data scientists, and developers to assess the quality, structure, and readiness of datasets through an intuitive, browser-based interface.

AIDRIN evaluates datasets across six dimensions:

- **Data Quality**
- **Data Governance**
- **Data Understandability and Usability**
- **Fairness and Bias**
- **Impact on AI**
- **Data Structure and Organization**

.. image:: _static/pillars.png
   :alt: Pillars of Data Readiness for AI
   :align: center
   :width: 80%

----

Two Ways to Use AIDRIN
-----------------------

**Web Interface**
   An interactive, browser-based dashboard. Upload a dataset, select dimensions and metrics, and
   explore results with visualizations and downloadable reports — no coding required. Available
   hosted at `aidrin.io <https://aidrin.io>`_ or self-hosted locally.
   See :ref:`web_installation` and :ref:`web_usage`.

**Command Line Interface (CLI)**
   Run data readiness metrics directly from your terminal or Python scripts. Suitable for
   automated pipelines, CI workflows, and headless environments. Also includes an **agentic
   evaluation** component for domain-aware data readiness question answering and remediation
   grounded in scientific literature.
   See :ref:`cli_installation` and :ref:`cli_usage`.

----

.. toctree::
   :maxdepth: 2
   :caption: Web Interface

   web_installation
   web_usage

.. toctree::
   :maxdepth: 2
   :caption: CLI Interface

   cli_installation
   cli_usage

.. toctree::
   :maxdepth: 2
   :caption: More

   appfl_integration
   testing
   contributing
   limitations
   publications
