# docs/conf.py
import datetime

"""Sphinx configuration."""
project = "FOLIO Data Import"
author = "EBSCO Information Services"
copyright = f"{datetime.date.today().year}, {author}"

# Source directory configuration
source_dir = "source"
master_doc = "index"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx_autodoc_typehints",
    "sphinx_design",
]

# Napoleon settings for Google-style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True
html_theme = "sphinx_book_theme"
myst_heading_anchors = 3
html_theme_options = {
    "repository_url": "https://github.com/folio-fse/folio_data_import",
    "use_repository_button": True,
    "show_navbar_depth": 2,
    "max_navbar_depth": 3,
    "show_nav_level": 2,
    "collapse_navigation": True,
}
myst_enable_extensions = [
    "deflist",
    "colon_fence",
]

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_member_order = "bysource"

source_suffix = {
    ".rst": "restructuredtext",
    ".txt": "markdown",
    ".md": "markdown",
}
