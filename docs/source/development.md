# Development

This guide covers development workflow, testing, and documentation for FOLIO Data Import.

## Environment Setup

### Prerequisites

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and virtual environments. Install uv first:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 1. Clone Repository

```bash
git clone https://github.com/FOLIO-FSE/folio_data_import.git
cd folio_data_import
```

### 2. Install Dependencies

uv automatically creates and manages the virtual environment:

```bash
# Install all dependencies including dev group
uv sync

# Or install with docs dependencies as well
uv sync --group docs
```

The virtual environment is created at `.venv/` and activated automatically when using `uv run`.

### 3. Running Commands

Use `uv run` to execute commands in the project environment:

```bash
# Run a Python script
uv run python script.py

# Run the CLI tools
uv run folio-batch-poster --help
uv run folio-marc-import --help
uv run folio-user-import --help

# Run pytest
uv run pytest
```

## Running Tests

### Basic Test Run

```bash
uv run pytest
```

### With Coverage Report

```bash
uv run pytest --cov=folio_data_import --cov-report=html
```

Open `htmlcov/index.html` to view coverage details.

### Specific Test File

```bash
uv run pytest tests/test_batch_poster.py -v
```

### Running Specific Test

```bash
uv run pytest tests/test_batch_poster.py::test_initialization -v
```

## Code Quality

This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting. Ruff is a fast Python linter and formatter written in Rust that replaces Black, Flake8, isort, and many other tools.

### Check Formatting

```bash
# Check if files are formatted correctly
uv run ruff format --check src/ tests/

# Format all files
uv run ruff format src/ tests/
```

### Linting

```bash
# Check for issues
uv run ruff check src/ tests/

# Fix issues automatically where possible
uv run ruff check src/ tests/ --fix

# Show what fixes would be applied
uv run ruff check src/ tests/ --show-fixes
```

### Run All Quality Checks

```bash
# Format code
uv run ruff format .

# Lint and auto-fix
uv run ruff check . --fix

# Run tests
uv run pytest
```

### Ruff Configuration

Ruff is configured in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 99
target-version = "py310"

[tool.ruff.lint]
select = ["B", "B9", "C", "E", "F", "S", "W"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

Key lint rule categories enabled:
- **B** - flake8-bugbear (common bugs)
- **C** - mccabe complexity
- **E/W** - pycodestyle errors and warnings
- **F** - pyflakes (undefined names, unused imports)
- **S** - flake8-bandit (security issues)

## Project Structure

```
folio_data_import/
├── src/
│   └── folio_data_import/
│       ├── __init__.py
│       ├── __main__.py
│       ├── BatchPoster.py           # Inventory batch posting
│       ├── MARCDataImport.py        # MARC record import
│       ├── UserImport.py            # User data import
│       ├── _progress.py             # Progress tracking
│       ├── custom_exceptions.py     # Custom exception classes
│       └── marc_preprocessors/      # MARC preprocessing utilities
├── tests/
│   ├── test_batch_poster.py
│   ├── test_marc_data_import.py
│   ├── test_user_import.py
│   └── test_progress.py
├── docs/
│   ├── conf.py                      # Sphinx configuration
│   └── source/                      # Documentation source files
├── pyproject.toml                   # Project metadata & tool config
├── pytest.ini                       # Pytest configuration
└── README.md
```

## Key Files

### `pyproject.toml`

Project configuration including:
- Project metadata and version
- Dependencies and dependency groups
- Build system configuration (uses `uv_build`)
- Tool configurations (ruff, pytest)

### `src/folio_data_import/`

Main package source code:

- **BatchPoster.py** - Core batch posting functionality for Instances, Holdings, Items
- **MARCDataImport.py** - MARC record import via FOLIO's Change Manager APIs
- **UserImport.py** - User data import via FOLIO's User Import API
- **_progress.py** - Progress reporting utilities (Rich-based CLI, Redis backend)
- **custom_exceptions.py** - Custom exception definitions

### `tests/`

Test suite:

- Unit tests for each module
- Test utilities

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/my-feature
```

Branch naming conventions:
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation changes
- `refactor/description` - Code refactoring

### 2. Make Your Changes

```bash
# Edit files in src/folio_data_import/
# Add tests in tests/

# Format code
uv run ruff format src/ tests/

# Lint and fix
uv run ruff check src/ tests/ --fix

# Run tests
uv run pytest
```

### 3. Commit and Push

```bash
git add .
git commit -m "Clear description of changes"
git push origin feature/my-feature
```

### 4. Create Pull Request

Go to GitHub and create a PR with:
- Clear title
- Description of changes
- Link to related issues
- Any testing instructions

## Documentation

### Building Documentation

```bash
# Install docs dependencies
uv sync --group docs

# Build HTML documentation
cd docs
uv run sphinx-build -b html -d _build/doctrees -c . source _build/html
```

Open `docs/_build/html/index.html` in a browser.

### Live Reload During Development

For faster documentation iteration:

```bash
cd docs
uv run sphinx-autobuild -b html -d _build/doctrees -c . source _build/html
```

This watches for changes and auto-rebuilds.

### Editing Documentation

Documentation source files are in `docs/source/` as Markdown (via MyST parser):

```markdown
# Title

Paragraph with introduction.

## Section

Details about the section.

### Subsection

More specific details.
```

### Adding API Documentation

Use Google-style docstrings for automatic API documentation:

```python
def my_function(param1: str, param2: int = 5) -> bool:
    """Brief description.

    Longer description with details.

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 5.

    Returns:
        Description of return value.

    Raises:
        ValueError: When validation fails.

    Example::

        result = my_function("test", param2=10)

    """
```

## Release Process

### Version Bump

Update version in `pyproject.toml`:

```toml
[project]
version = "0.6.0"
```

### Create a GitHub Release

1. Go to the [Releases page](https://github.com/FOLIO-FSE/folio_data_import/releases)
2. Click **Draft a new release**
3. Create a new tag (e.g., `v0.6.0`) or select an existing one
4. Add release notes describing the changes
5. Click **Publish release**

### Publishing to PyPI

This project uses [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/) via GitHub Actions. When you publish a new GitHub Release, the CI workflow automatically:

1. Builds the package
2. Publishes to PyPI using OIDC authentication

**Do not publish directly** - create a GitHub Release and let CI handle the PyPI upload.

## Debugging

### Logging

```python
import logging

logger = logging.getLogger(__name__)
logger.debug("Debug message: %s", variable)
```

Run with debug logging:

```bash
uv run pytest --log-level=DEBUG
```

### Interactive Debugging

Use the built-in debugger:

```python
breakpoint()  # Python 3.7+ built-in
```

Or with pytest:

```bash
uv run pytest --pdb  # Drop into debugger on failure
```

## Useful Commands

```bash
# List all test files
uv run pytest --collect-only

# Run with detailed output
uv run pytest -vv

# Run tests in parallel (install pytest-xdist)
uv run pytest -n auto

# Generate coverage report
uv run pytest --cov --cov-report=html

# Update all dependencies to latest compatible versions
uv lock --upgrade

# Add a new dependency
uv add package-name

# Add a dev dependency
uv add --group dev package-name

# Show dependency tree
uv tree
```

## Getting Help

- Check existing issues and discussions
- Review code in related modules
- Ask in pull request comments
- Contact a maintainer

## See Also

- [Contributing Guide](contributing.md)
- [API Reference](api_reference.rst)
- [Examples](examples.md)
