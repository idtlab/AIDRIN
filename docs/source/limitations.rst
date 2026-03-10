.. _limitations:

Limitations and Data Privacy
============================

This page outlines the current limitations of **AIDRIN** and clarifies what the system can and cannot do.
It also explains constraints on file sizes, supported formats, and privacy considerations.

Current Capabilities
--------------------

AIDRIN provides several core functionalities to assess and enhance dataset readiness:

- Evaluation of **dataset readiness** across multiple dimensions. See the `Key Features <index.html#key-features>`_ section for details.
- **Metadata analysis** for FAIR principles (Findable, Accessible, Interoperable, Reusable).
- Interactive **web-based dashboards** and Python API access for programmatic analyses.

What We Can Do
~~~~~~~~~~~~~~

- Provide **quantitative metrics** for dataset readiness and visualizations of results.
- Analyze **DCAT and DataCite JSON metadata** for FAIR compliance.
- Identify **missing or incomplete metadata elements**.
- Work with **structured tabular datasets** (e.g., CSV, Excel) for basic data readiness checks.

What We Cannot Do
~~~~~~~~~~~~~~~~~

- Validate the **factual accuracy** of dataset content (e.g., correctness of values or labels).
- Process **very large datasets** beyond system-imposed limits (see below).
- Automatically fix or transform datasets.
- Guarantee compliance with every possible **domain-specific standard**.

File and Size Limits
--------------------

- Maximum supported file size: **100 MB per file** (web interface may vary depending on server resources).
- If a file exceeds the limits, the system will time out.

Data Privacy and Storage
------------------------

- **AIDRIN does not store your uploaded data**.
- The `Clear Submission` button on the top right corner of the web interface allows you to remove all uploaded files from the system.
- All dataset processing is **temporary and session-based**.
- Uploaded files are **discarded after analysis**, ensuring data confidentiality.

.. note::

   While AIDRIN performs extensive automated checks and analyses, it is **advisory in nature**. Users should review the results and make decisions based on their domain knowledge.
