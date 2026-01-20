# Contributing

Thank you for your interest in contributing to FOLIO Data Import! This document explains how to get involved.

## Code of Conduct

We are committed to providing a welcoming and inspiring community for all. Please read and follow our Code of Conduct.

## How Can I Contribute?

### Reporting Bugs

Found a bug? Please report it on our [GitHub Issue tracker](https://github.com/FOLIO-FSE/folio_data_import/issues).

When reporting a bug, please include:

- **Description** - What happened vs. what you expected
- **Steps to reproduce** - Clear steps to recreate the issue
- **Logs** - Error messages and relevant logs (sanitized for sensitive data)
- **Environment** - Python version, OS, FOLIO version
- **Data sample** - Small sample data that demonstrates the issue (if applicable)

### Suggesting Enhancements

Have an idea for improvement? Open an issue with:

- **Description** - What feature you'd like and why
- **Use case** - Why this would be useful
- **Alternatives** - Any alternative approaches you've considered
- **Example** - Code example showing how it would be used

### Pull Requests

We welcome pull requests for bug fixes and features. To contribute code:

1. [Fork the repository](https://github.com/FOLIO-FSE/folio_data_import/fork)
2. Create a branch for your feature: `git checkout -b feature/my-feature`
3. Make your changes
4. Add tests if applicable
5. Update documentation
6. Commit with clear messages: `git commit -m "Add feature description"`
7. Push to your fork
8. Create a pull request with a clear description

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

1. Clone the repository:

```bash
git clone https://github.com/FOLIO-FSE/folio_data_import.git
cd folio_data_import
```

2. Install dependencies with uv:

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (creates .venv automatically)
uv sync
```

## Code Standards

### Style

We follow PEP 8 with some modifications:

- Line length: 99 characters
- Use double quotes for strings
- Use type hints where practical

We use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting:

```bash
# Format code
uv run ruff format src/ tests/

# Lint code and auto-fix where possible
uv run ruff check src/ tests/ --fix
```

### Documentation

All public functions and classes should have docstrings:

```python
def post_records(self, batch_size: int = 250) -> dict:
    """Post all records to FOLIO.
    
    Args:
        batch_size: Number of records per API request.
        
    Returns:
        Dictionary with keys 'success', 'failed', 'errors'.
        
    Raises:
        BatchPosterException: If posting fails.
    """
```

## Testing

Write tests for new features and bug fixes.

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=folio_data_import

# Run specific test file
uv run pytest tests/test_batch_poster.py

# Run with verbose output
uv run pytest -v
```

### Writing Tests

Create test files in the `tests/` directory:

```python
import pytest
from folio_data_import import BatchPoster

def test_batch_poster_initialization():
    """Test BatchPoster initialization."""
    poster = BatchPoster(
        okapi_url="https://example.com",
        tenant_id="test",
        username="admin",
        password="secret",
        record_file="test.json",
        object_type="Instances"
    )
    assert poster.okapi_url == "https://example.com"
```

## Documentation

### Building Documentation

Build the documentation locally:

```bash
uv sync --group docs
cd docs
uv run sphinx-build -b html -d _build/doctrees -c . source _build/html
```

Open `_build/html/index.html` in your browser.

### Writing Documentation

Documentation files go in `docs/source/` as Markdown:

- Use clear, accessible language
- Include code examples
- Link to related sections
- Keep paragraphs short

## Pull Request Process

1. Update documentation and tests
2. Ensure all tests pass: `uv run pytest`
3. Format and lint: `uv run ruff format . && uv run ruff check . --fix`
4. Build documentation locally: `cd docs && uv run sphinx-build -b html -d _build/doctrees -c . source _build/html`
5. Create a detailed pull request with:
   - Clear description of changes
   - Reference to any related issues
   - Screenshots if UI changes
   - Any breaking changes clearly noted

## Commit Messages

Write clear, descriptive commit messages:

```
Add feature: Brief description

Longer description of what was changed and why,
spanning multiple lines if needed.

Fixes #123
```

## Questions?

Have questions about contributing? Feel free to:

- Open an issue with your question
- Check existing issues and discussions
- Contact a maintainer

## Code Ownership

When you contribute code to this project, you agree that:

- Your code can be used under the project's license (MIT)
- You have the right to contribute the code
- Your contributions are original

Thank you for helping improve FOLIO Data Import!

## Related Resources

- [Development Guide](development.md)
- [Repository](https://github.com/FOLIO-FSE/folio_data_import)
- [Issue Tracker](https://github.com/FOLIO-FSE/folio_data_import/issues)
- [FOLIO Project](https://www.folio.org/)
