# Installing

## Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) package manager (recommended) or pip

## Installation

### 1. Using uv (recommended)

Create a virtual environment and install with uv:

```bash
uv venv                       # Create virtual environment
source .venv/bin/activate     # Activate on macOS/Linux
# or on Windows:
.venv\Scripts\activate

uv pip install folio-data-import
```

### 2. Using pip and a virtual environment

Alternatively, create a virtual environment and install with pip:

```bash
python -m venv .venv          # Create virtual environment
source .venv/bin/activate     # Activate on macOS/Linux
# or on Windows:
.venv\Scripts\activate

pip install folio-data-import
```

### 3. Development installation

To install in development mode for contributing:

```bash
git clone https://github.com/FOLIO-FSE/folio_data_import.git
cd folio_data_import

# Using uv (recommended):
uv venv                       # Create virtual environment
source .venv/bin/activate     # Activate on macOS/Linux
# or on Windows:
.venv\Scripts\activate

uv pip install -e .

# Or using pip:
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. With optional Redis support

To use progress tracking with Redis:

```bash
# Using uv:
uv pip install folio-data-import[redis]

# Using pip:
pip install folio-data-import[redis]
```

### 5. CLI-only installation (no virtual environment)

If you only need the command-line tools and don't plan to use the Python API, install them system-wide with uv:

```bash
uv tool install folio-data-import
```

This installs the CLI command (`folio-data-import`) and sub-commands (`batch-poster`, `marc`, `users`) in an isolated environment, making them available globally without activating a virtual environment. Perfect for scripting and automation.

To update later:

```bash
uv tool upgrade folio-data-import
```

## Verify Installation

Test that the tools are installed correctly:

```bash
folio-data-import --help
folio-data-import batch-poster --help
folio-data-import marc --help
folio-data-import users --help
```

Each command should display help information showing available options.

## Next Steps

Ready to get started? Check out the [Quick Start Tutorial](quick_start.md) for a simple walkthrough.
