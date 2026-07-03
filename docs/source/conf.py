# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os

# Read the version from aidrin/_version.py directly (without importing the
# package) so the docs build works without aidrin and its deps installed.
_version_globals = {}
_version_path = os.path.join(os.path.dirname(__file__), "..", "..", "aidrin", "_version.py")
with open(_version_path) as _version_file:
    exec(_version_file.read(), _version_globals)

project = 'AIDRIN'
copyright = '2025, IDT Lab'
author = 'IDT Lab'
release = _version_globals["__version__"]

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = []

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'

html_theme_options = {
    'style_nav_header_background': '#efefef',
    'logo_only': True,
    'collapse_navigation': False,
    'navigation_depth': 2,
    'sticky_navigation': True,
}

html_logo = "_static/logo.png"
html_static_path = ['_static']
html_css_files = ['css/aidrin.css']
