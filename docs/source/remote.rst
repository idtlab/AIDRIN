.. _remote:

Remote datasets with Globus Compute
===================================

AIDRIN can run its metrics on a machine you do not have to copy data off of, by
submitting the work to a `Globus Compute <https://www.globus.org/compute>`_
endpoint. Only the results travel back.

Requirements
------------

* ``pip install 'aidrin[globus]'`` on your machine.
* A running Globus Compute endpoint on the remote machine, with ``aidrin``
  installed in the endpoint's Python environment.
* The dataset already on a filesystem that endpoint can read. AIDRIN does not
  transfer data.

One-time setup
--------------

.. code-block:: bash

   aidrin remote configure --name nersc --endpoint <endpoint-uuid>

This logs in through Globus if needed (tokens are cached by
``globus-compute-sdk``), probes the endpoint, and refuses to save if the
endpoint cannot import ``aidrin.headless.api``. Add ``--local`` to write
``./.aidrin.json`` for the current project instead of ``~/.aidrin/config.json``.

Running metrics
---------------

.. code-block:: bash

   aidrin remote summarize /scratch/proj/data.csv
   aidrin remote data-quality /scratch/proj/data.csv
   aidrin remote run k-anonymity /scratch/proj/data.csv "zip,age"
   aidrin remote batch config.yaml

Every command takes the same arguments as its local counterpart and prints the
same JSON. Paths inside those arguments refer to the endpoint's filesystem —
for example ``/scratch/proj/data.csv`` above.

The one exception is ``aidrin remote batch``: ``config.yaml`` is a path on
*your* machine and is read locally, same as ``aidrin batch``. Only the
``file-path`` value written inside that config must be visible on the
endpoint.

Long-running jobs
-----------------

.. code-block:: bash

   aidrin remote run k-anonymity /scratch/data.csv "zip,age" --async
   # prints {"task_id": "..."}
   aidrin remote task <task-id>          # status
   aidrin remote task <task-id> --wait   # block for the result

Choosing an endpoint
--------------------

Precedence, first match wins:

1. ``--endpoint <uuid>``
2. ``--profile <name>``
3. ``AIDRIN_GLOBUS_ENDPOINT``
4. the default profile in ``./.aidrin.json``
5. the default profile in ``~/.aidrin/config.json``

``aidrin remote`` never falls back to running locally. If no endpoint resolves,
it exits with an error.

Limitations
-----------

* Custom metrics, remedies, and the agentic pipeline are local-only.
* Results are capped near 10 MB, so visualization payloads are stripped unless
  you ask for images.
* Images are written on your machine, never on the endpoint.
