.. _hpc:

HPC Systems (NERSC and SDSC)
============================

On NERSC Perlmutter and SDSC Expanse you can run the ``aidrin`` CLI as an environment module,
without installing Python packages. The module is a small wrapper that runs the public AIDRIN
container image (``aidrin/aidrin`` on Docker Hub), with Shifter on Perlmutter and Singularity on
Expanse. Each user sets up the module once in their home directory.

.. note::

   Expanse support is being tested with SDSC. If a step below fails on Expanse, please
   `open an issue <https://github.com/idtlab/AIDRIN/issues>`_ with the command and its output.

The module provides the CLI only. To use AIDRIN as a Python library, install it with ``pip``
(see :ref:`cli_installation`).

----

Set Up on Perlmutter
--------------------

On a login node:

.. code-block:: bash

   shifterimg pull aidrin/aidrin:|AIDRIN_VERSION_TAG|
   curl -sL https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/configure-module.sh \
       | bash -s perlmutter |AIDRIN_VERSION| docker:aidrin/aidrin:|AIDRIN_VERSION_TAG| ~/aidrin-modules

Then load the module, and add the ``module use`` line to your ``~/.bashrc`` so it is available
in every session:

.. code-block:: bash

   module use ~/aidrin-modules/modulefiles
   module load aidrin
   aidrin list

Set Up on Expanse
-----------------

Building the Singularity image is too heavy for a login node, so start a short interactive job
first (replace ``<account>`` with your allocation):

.. code-block:: bash

   srun --account=<account> --partition=debug --nodes=1 --ntasks-per-node=4 --mem=16G \
       -t 00:30:00 --pty /bin/bash

Then pull the image and configure the module:

.. code-block:: bash

   module load singularitypro
   export SINGULARITY_CACHEDIR=/scratch/$USER/job_$SLURM_JOB_ID
   singularity pull ~/aidrin-|AIDRIN_VERSION|.sif docker://aidrin/aidrin:|AIDRIN_VERSION_TAG|
   curl -sL https://raw.githubusercontent.com/idtlab/AIDRIN/develop/hpc/configure-module.sh \
       | bash -s expanse |AIDRIN_VERSION| ~/aidrin-|AIDRIN_VERSION|.sif ~/aidrin-modules

Load it the same way as on Perlmutter. The module loads ``singularitypro`` for you:

.. code-block:: bash

   module use ~/aidrin-modules/modulefiles
   module load aidrin
   aidrin list

----

Running AIDRIN
--------------

Once the module is loaded, ``aidrin`` works exactly as described in :ref:`cli_usage`. Keep
datasets on ``$SCRATCH`` or the Community File System on Perlmutter, and under
``/expanse/lustre`` on Expanse. The container sees those file systems and your home directory.

Login nodes limit CPU and memory per user, so run real assessments in a job. For example, on
Perlmutter:

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

On Expanse, request memory explicitly (the default is 1 GB per core) and add the ``lustre``
constraint when your data is on Lustre. Without it the job can land on a node that has no
Lustre and fails:

.. code-block:: bash

   #!/bin/bash
   #SBATCH --account=<account>
   #SBATCH --partition=shared
   #SBATCH --nodes=1
   #SBATCH --ntasks-per-node=8
   #SBATCH --mem=64G
   #SBATCH --constraint="lustre"
   #SBATCH -t 00:30:00

   module use ~/aidrin-modules/modulefiles
   module load aidrin

   cd /expanse/lustre/scratch/$USER/temp_project/my-project
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
tags (``|AIDRIN_VERSION_TAG|``); module versions are the same number without the ``v``. Older versions stay available until
you remove them, and ``module load aidrin/<version>`` selects a specific one. ``configure-module.sh``
does not overwrite a version that is already configured.

To also get the MCP server (``aidrin-mcp``, see :ref:`aidrin_skill`), use the ``-mcp`` image and
version, for example ``aidrin/aidrin:|AIDRIN_VERSION_TAG|-mcp`` and ``|AIDRIN_VERSION|-mcp``. That image is larger
because it includes the agentic stack.

----

Limitations
-----------

* **One node, in memory.** AIDRIN reads the whole dataset into memory on one node, so it must fit
  in that node's RAM: 512 GB on a Perlmutter CPU node, 256 GB on an Expanse standard node, and
  2 TB on an Expanse ``large-shared`` node. AIDRIN does not use GPUs.
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
