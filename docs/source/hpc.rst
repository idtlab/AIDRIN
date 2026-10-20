.. _hpc:

HPC Systems (NERSC)
===================

On NERSC Perlmutter you can run the ``aidrin`` CLI as an environment module, without installing
Python packages. The module is a small wrapper that runs the public AIDRIN container image
(``aidrin/aidrin`` on Docker Hub) with Shifter. Each user sets up the module once in their home
directory.

The module provides the CLI only. To use AIDRIN as a Python library, install it with ``pip``
(see :ref:`cli_installation`).

----

Set Up on Perlmutter
--------------------

On a login node:

.. code-block:: bash

   shifterimg pull aidrin/aidrin:v2026.09.1
   curl -sL https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/configure-module.sh \
       | bash -s perlmutter 2026.09.1 docker:aidrin/aidrin:v2026.09.1 ~/aidrin-modules

Then load the module, and add the ``module use`` line to your ``~/.bashrc`` so it is available
in every session:

.. code-block:: bash

   module use ~/aidrin-modules/modulefiles
   module load aidrin
   aidrin list

----

Running AIDRIN
--------------

Once the module is loaded, ``aidrin`` works exactly as described in :ref:`cli_usage`. Keep
datasets on ``$SCRATCH`` or the Community File System. The container sees those file systems
and your home directory.

Login nodes limit CPU and memory per user, so run real assessments in a job. For example:

.. code-block:: bash

   #!/bin/bash
   #SBATCH -A <account>
   #SBATCH -q regular
   #SBATCH -C cpu
   #SBATCH -N 1
   #SBATCH -t 00:30:00

   module use ~/aidrin-modules/modulefiles
   module load aidrin

   cd $SCRATCH/my-project
   aidrin batch config.yaml > results.json

When ``aidrin batch`` saves plots, set ``image_dir`` in the config to a directory you own:

.. code-block:: yaml

   file-path: /pscratch/sd/u/user/my-project/data.csv
   image_dir: /pscratch/sd/u/user/my-project/images
   metrics:
     - completeness

----

New Versions
------------

Run the same setup commands with the new version number. Image tags match the AIDRIN release
tags (``v2026.09.1``); module versions are the same number without the ``v``. Older versions stay available until
you remove them, and ``module load aidrin/<version>`` selects a specific one. ``configure-module.sh``
does not overwrite a version that is already configured.

To also get the MCP server (``aidrin-mcp``, see :ref:`aidrin_skill`), use the ``-mcp`` image and
version, for example ``aidrin/aidrin:v2026.09.1-mcp`` and ``2026.09.1-mcp``. That image is larger
because it includes the agentic stack.

----

Limitations
-----------

* **One node, in memory.** AIDRIN reads the whole dataset into memory on one node, so it must fit
  in that node's RAM, 512 GB on a Perlmutter CPU node. AIDRIN does not use GPUs.
* **Plots are node-local by default.** Without ``image_dir``, ``aidrin batch`` writes plots to
  ``/tmp/aidrin_images``, which is local to the node. If another user created that directory
  first, the plots are silently dropped.
* **Many datasets at once.** Run separate processes, for example a Slurm job array, and set
  ``OMP_NUM_THREADS`` to the cores each process should use. The module passes it through to
  the container.
* **Custom metrics** (``aidrin run custom``) run with the container's Python, so they can only
  import packages that are in the image. Remedies write next to the script, so its directory
  must be writable.
* **The MCP variant** sends dataset samples and schema to an external LLM. Do not use it on
  data that must not leave the system, such as HIPAA-covered or CUI data.

----

Maintainers
-----------

Building and publishing the image, and installing a shared module for a whole project, are
described in ``hpc/README.md`` in the repository. ``hpc/smoke-test.sh`` checks an installed
module from any directory.
