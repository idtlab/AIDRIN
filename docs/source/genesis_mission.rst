Genesis Mission (AmSC)
======================

The American Science Cloud (AmSC) hosts a shared MLflow deployment at
``https://mlflow.american-science-cloud.org``. AIDRIN records dataset readiness
assessments there, so that the readiness of a dataset is tracked alongside the
experiments and model runs that consume it.

This page covers what you need in order to point AIDRIN at AmSC. For what AIDRIN
records and why, see :doc:`mlflow_tracking`.

.. contents::
   :local:
   :depth: 2


Why track readiness on AmSC
---------------------------

A readiness assessment is most useful next to the work it informs. Recording
assessments on the same deployment that holds your experiment runs gives you
three things.

First, a dataset's readiness becomes comparable over time: each assessment is one
row, and the scores for two versions of a dataset sit side by side in the same
table. Second, AIDRIN identifies a dataset by the same digest MLflow itself
computes, so an assessment and a training run over that file resolve to a single
dataset, and you can move from a model run to the readiness of the data behind
it. Third, the assessment travels with its interpretation, because the report
you write is attached to the run rather than living in a directory somewhere
else.


Setting up
----------

Obtain an API key for the deployment. AmSC accounts are managed at
https://profile.american-science-cloud.org, which accepts Google and Globus
sign-in; follow your local AmSC guidance for how keys are issued to your
project.

Store the key in a file rather than in your shell history or a script:

.. code-block:: bash

   umask 077 && cat > ~/.amsc-key    # paste the key, then press Ctrl-D

Configure AIDRIN:

.. code-block:: bash

   export MLFLOW_TRACKING_URI=https://mlflow.american-science-cloud.org
   export AIDRIN_MLFLOW_AUTH_HEADER=x-api-key
   export AIDRIN_MLFLOW_AUTH_KEY="$(cat ~/.amsc-key)"
   export AIDRIN_MLFLOW_ENABLED=1
   export AIDRIN_MLFLOW_EXPERIMENT=my-experiment
   export MLFLOW_TRACKING_USERNAME='<your AmSC identity>'

The deployment sits behind an API gateway that expects your key in the
``x-api-key`` header, which is what ``AIDRIN_MLFLOW_AUTH_HEADER`` and
``AIDRIN_MLFLOW_AUTH_KEY`` provide. ``MLFLOW_TRACKING_USERNAME`` plays no part in
authentication on AmSC; AIDRIN uses it for the ``mlflow.user`` tag, so that your
runs are attributed to your AmSC identity rather than to the account name on your
laptop.

Verify the configuration before running an assessment:

.. code-block:: bash

   aidrin list --capabilities

The response reports ``mlflow_enabled: true`` and the experiment name when
everything is in place.

Run an assessment:

.. code-block:: bash

   aidrin data-quality data.csv
   aidrin batch config.yaml --report report.md

Artifacts are proxied by the AmSC server, so result archives and reports upload
without any additional cloud credentials.


Working on shared infrastructure
--------------------------------

AmSC is shared, and your runs sit beside those of other groups. Two
consequences are worth planning for.

**Choose an experiment name deliberately.** AIDRIN creates
``AIDRIN_MLFLOW_EXPERIMENT`` when it does not already exist, and gives a new
experiment a description identifying it as AIDRIN output. Follow whatever naming
convention your deployment uses rather than the ``aidrin`` default, and check
with the deployment owners before creating experiments.

**Decide what metadata you are willing to publish.** By default AIDRIN records
real file names, the column arguments each metric received, and a redacted
``result.json`` for every metric. Cell values, PII and PHI matches, and error
text are never recorded, but column names alone can be revealing. For a first
run, or for anything sensitive, turn dataset details off:

.. code-block:: bash

   export AIDRIN_MLFLOW_LOG_DATA_DETAILS=0

AIDRIN then hashes dataset paths, withholds column names, and skips result
archives, while still recording every readiness score.


Troubleshooting
---------------

**Every request returns 401 with "Please log in ... Error: Anonymous".** The
gateway did not receive a usable key. Confirm that both
``AIDRIN_MLFLOW_AUTH_HEADER=x-api-key`` and ``AIDRIN_MLFLOW_AUTH_KEY`` are set in
the environment where AIDRIN runs. The standard MLflow variables
(``MLFLOW_TRACKING_TOKEN``, ``MLFLOW_TRACKING_PASSWORD``) do not authenticate to
this deployment, because the gateway expects a named header rather than an
``Authorization`` header.

**Runs are attributed to your laptop account.** Set
``MLFLOW_TRACKING_USERNAME`` to your AmSC identity.

**A key stops working.** Keys may expire or be revoked; request a new one through
your AmSC account. Rotate a key immediately if it has appeared in a shell
transcript, a log, or a commit.

For anything else, see the troubleshooting section of :doc:`mlflow_tracking`.
