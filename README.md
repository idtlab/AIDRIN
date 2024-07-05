AIDRIn
======

A tool developed to evaluate the readiness of your data for AI


Install
-------

    # clone the repository
    $ git clone https://github.com/idtlab/AIDRIN.git
    $ cd aidrin

Create a virtualenv and activate it::

    $ python3 -m venv .venv
    $ . .venv/bin/activate

Or on Windows cmd::

    $ py -3 -m venv .venv
    $ .venv\Scripts\activate.bat

Install AIDRIN::

    # go to the AIDRIN directory
    $ cd ..
    $ pip install -e .

Run
---

    $ flask --app aidrin run --debug

Open http://127.0.0.1:5000 in a browser.
