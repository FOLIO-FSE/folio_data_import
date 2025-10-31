import importlib.metadata
import questionary


def get_folio_connection_parameters(
    gateway_url: str | None, tenant_id: str | None, username: str | None, password: str | None
) -> tuple[str, str, str, str]:
    """
    Prompt for missing FOLIO connection parameters using interactive input.

    Parameters:
        gateway_url (str): The FOLIO Gateway URL, or None to prompt for input.
        tenant_id (str): The FOLIO Tenant ID, or None to prompt for input.
        username (str): The FOLIO Username, or None to prompt for input.
        password (str): The FOLIO password, or None to prompt for input.

    Returns:
        tuple: A tuple containing (gateway_url, tenant_id, username, password).
    """
    if not gateway_url:
        gateway_url = questionary.text("Enter FOLIO Gateway URL:").ask()
    if not tenant_id:
        tenant_id = questionary.text("Enter FOLIO Tenant ID:").ask()
    if not username:
        username = questionary.text("Enter FOLIO Username:").ask()
    if not password:
        password = questionary.password("Enter FOLIO password:").ask()
    return gateway_url, tenant_id, username, password


__version__ = importlib.metadata.version("folio-data-import")
