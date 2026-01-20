```{toctree}
:maxdepth: 3
:caption: Getting Started
:hidden:
installing.md
quick_start.md
concepts.md
```

```{toctree}
:maxdepth: 3
:hidden:
:caption: Using the Tools
batch_poster_guide.md
user_import_guide.md
marc_data_import_guide.md
marc_preprocessors.md
examples.md
troubleshooting.md
```

```{toctree}
:maxdepth: 2
:hidden:
:caption: Reference
api_reference
```

```{toctree}
:maxdepth: 2
:hidden:
:caption: Contributing
contributing.md
development.md
```

# FOLIO Data Import

A Python toolkit for bulk importing data into a FOLIO LSP environment. Currently supports:

- **MARC records** - Import bibliographic and holdings MARC records
- **User/patron data** - Load user records from JSON Lines format
- **Batch operations** - Post data to FOLIO using the API

## What does it do?

FOLIO Data Import provides utilities and tools to help with initial data migrations into FOLIO, as well as ongoing bulk imports.

## Key Features

- **MARC Import** - Load batches of MARC records via FOLIO's Data Import system using change-manager APIs
- **User Import** - An alternative to FOLIO's own `user-import` API that offers more robust record handling and extended functionality (field protection, service point assignment, etc.)
- **Batch Posting** - Efficiently post Inventory records to FOLIO using batch APIs
- **Progress Tracking** - Real-time progress reporting with Redis support
- **Error Reporting** - Detailed error logs and failed record tracking
- **Flexible Configuration** - JSON configuration files for all tools

## Quick Links

- **[Installation Guide](installing.md)** - Get started with pip or development setup
- **[Quick Start Tutorial](quick_start.md)** - Simple examples to get you running
- **[API Reference](api_reference.rst)** - Complete Python API documentation
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions

## Contributing

Found a bug? Want to contribute a feature? Check out the [Contributing Guide](contributing.md) to learn how to help improve FOLIO Data Import.

## Found an issue?

Report it on the [GitHub Issue tracker](https://github.com/FOLIO-FSE/folio_data_import/issues)

---

{sub-ref}`today` | {sub-ref}`wordcount-words` words | {sub-ref}`wordcount-minutes` min read
