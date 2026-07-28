import asyncio
import datetime
import glob
import json
import logging
import sys
import time
import uuid
from datetime import datetime as dt
from io import TextIOWrapper
from pathlib import Path
from typing import Annotated, Any, List, Literal, Tuple

import aiofiles
import cyclopts
import folioclient
import httpx
from aiofiles.threadpool.text import AsyncTextIOWrapper
from pydantic import BaseModel, Field

from folio_data_import import (
    DATA_ISSUE_LVL_NUM,
    get_folio_connection_parameters,
    set_up_cli_logging,
)
from folio_data_import._progress import (
    NoOpProgressReporter,
    ProgressReporter,
    RichProgressReporter,
)

try:
    utc = datetime.UTC
except AttributeError:
    import zoneinfo

    utc = zoneinfo.ZoneInfo("UTC")

logger = logging.getLogger(__name__)

# Mapping of preferred contact type IDs to their corresponding values
PREFERRED_CONTACT_TYPES_MAP = {
    "001": "mail",
    "002": "email",
    "003": "text",
    "004": "phone",
    "005": "mobile",
}
PREFERRED_CONTACT_TYPES_NAME_TO_ID = {v: k for k, v in PREFERRED_CONTACT_TYPES_MAP.items()}


USER_MATCH_KEYS = ["username", "barcode", "externalSystemId"]
PROTECTED_USER_TYPES = ["staff", "system", "shadow", "dcb"]


class UserImporterStats(BaseModel):
    """Statistics for user import operations."""

    created: int = 0
    updated: int = 0
    failed: int = 0
    deleted: int = 0


class UserImporter:  # noqa: R0902
    """
    Class to import mod-user-import compatible user objects
    (eg. from folio_migration_tools UserTransformer task)
    from a JSON-lines file into FOLIO
    """

    class Config(BaseModel):
        """Configuration for UserImporter operations."""

        library_name: Annotated[
            str,
            Field(
                title="Library name",
                description="The library name associated with the import job",
            ),
        ]
        batch_size: Annotated[
            int,
            Field(
                title="Batch size",
                description="Number of users to process in each batch",
                ge=1,
                le=1000,
            ),
        ] = 250
        user_match_key: Annotated[
            Literal["externalSystemId", "username", "barcode"],
            Field(
                title="User match key",
                description="The key to use for matching existing users",
            ),
        ] = "externalSystemId"
        only_update_present_fields: Annotated[
            bool,
            Field(
                title="Only update present fields",
                description=(
                    "When enabled, only fields present in the input will be updated. "
                    "Missing fields will be left unchanged in existing records."
                ),
            ),
        ] = False
        default_preferred_contact_type: Annotated[
            Literal["001", "002", "003", "004", "005", "mail", "email", "text", "phone", "mobile"],
            Field(
                title="Default preferred contact type",
                description=(
                    "Default preferred contact type for users. "
                    "Can be specified as ID (001-005) or name (mail/email/text/phone/mobile). "
                    "Will be applied to users without a valid value already set."
                ),
            ),
        ] = "002"
        fields_to_protect: Annotated[
            List[str],
            Field(
                title="Fields to protect",
                description=(
                    "List of field paths to protect from updates "
                    "(e.g., ['personal.email', 'barcode']). "
                    "Protected fields will not be modified during updates."
                ),
            ),
        ] = []
        limit_simultaneous_requests: Annotated[
            int,
            Field(
                title="Limit simultaneous requests",
                description="Maximum number of concurrent async HTTP requests",
                ge=1,
                le=100,
            ),
        ] = 10
        user_file_paths: Annotated[
            Path | List[Path] | None,
            Field(
                title="User file paths",
                description="Path or list of paths to JSON-lines file(s) containing user data",
            ),
        ] = None
        no_progress: Annotated[
            bool,
            Field(
                title="No progress bar",
                description="Disable the progress bar display",
            ),
        ] = False
        delete_all: Annotated[
            bool,
            Field(
                title="Delete all users in file(s)",
                description="Whether to delete existing users, rather than create/update.",
            ),
        ] = False
        delete_pus: Annotated[
            bool,
            Field(
                title="Delete permission user objects when deleting users",
                description=(
                    "Whether to delete associated permission user objects when deleting users."
                ),
            ),
        ] = False
        handle_permissions_user_objects: Annotated[
            bool,
            Field(
                title="Handle permission user objects",
                description="Whether to handle permission user objects when updating users.",
            ),
        ] = True

    logfile: AsyncTextIOWrapper
    errorfile: AsyncTextIOWrapper

    def __init__(
        self,
        folio_client: folioclient.FolioClient,
        config: "UserImporter.Config",
        reporter: ProgressReporter | None = None,
    ) -> None:
        self.config = config
        self.folio_client: folioclient.FolioClient = folio_client
        # Create reporter from config if not provided
        if reporter is None:
            self.reporter = (
                NoOpProgressReporter()
                if config.no_progress
                else RichProgressReporter(show_speed=True, show_time=True)
            )
        else:
            self.reporter = reporter
        self.delete_pus = config.delete_pus
        self.limit_simultaneous_requests = asyncio.Semaphore(config.limit_simultaneous_requests)
        # Build reference data maps (these need processing)
        self.patron_group_map: dict = self.build_ref_data_id_map(
            self.folio_client, "/groups", "usergroups", "group"
        )
        self.address_type_map: dict = self.build_ref_data_id_map(
            self.folio_client, "/addresstypes", "addressTypes", "addressType"
        )
        self.department_map: dict = self.build_ref_data_id_map(
            self.folio_client, "/departments", "departments", "name"
        )
        self.service_point_map: dict = self.build_ref_data_id_map(
            self.folio_client, "/service-points", "servicepoints", "code"
        )
        # Convert fields_to_protect to a set to dedupe
        self.fields_to_protect = set(config.fields_to_protect)
        self._http_client_override: Any | None = None
        self.lock: asyncio.Lock = asyncio.Lock()
        self.stats = UserImporterStats()

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Return the shared FolioClient async HTTP client for this import run."""
        if self._http_client_override is not None:
            return self._http_client_override
        async_httpx_client = getattr(self.folio_client, "async_httpx_client", None)
        if not async_httpx_client or async_httpx_client.is_closed:
            raise RuntimeError(
                "FolioClient async session is not initialized. "
                "Run UserImporter inside 'async with folio_client:'."
            )
        return async_httpx_client

    @http_client.setter
    def http_client(self, client: Any) -> None:
        """Allow explicit client injection for tests and controlled overrides."""
        self._http_client_override = client

    @staticmethod
    def build_ref_data_id_map(
        folio_client: folioclient.FolioClient, endpoint: str, key: str, name: str
    ) -> dict:
        """
        Builds a map of reference data IDs.

        Args:
            folio_client (folioclient.FolioClient): A FolioClient object.
            endpoint (str): The endpoint to retrieve the reference data from.
            key (str): The key to use as the map key.

        Returns:
            dict: A dictionary mapping reference data keys to their corresponding IDs.
        """
        return {x[name]: x["id"] for x in folio_client.folio_get_all(endpoint, key)}

    @staticmethod
    def validate_uuid(uuid_string: str) -> bool:
        """
        Validate a UUID string.

        Args:
            uuid_string (str): The UUID string to validate.

        Returns:
            bool: True if the UUID is valid, otherwise False.
        """
        try:
            uuid.UUID(uuid_string)
            return True
        except ValueError:
            return False

    @staticmethod
    def _serialize_data_issues_context(context: object) -> str:
        if context in (None, ""):
            return ""
        if isinstance(context, str):
            return context
        try:
            return json.dumps(context, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(context)

    @staticmethod
    def _get_nested_value(data: dict, path: str) -> str:
        current = data
        for part in path.split("."):
            if not isinstance(current, dict):
                return ""
            current = current.get(part)
        return current if isinstance(current, str) else ""

    def _get_user_record_identifier(self, user_obj: dict, line_number: int | None = None) -> str:
        candidate_keys = ["id", self.config.user_match_key, *USER_MATCH_KEYS]
        seen = set()
        for key in candidate_keys:
            if key in seen:
                continue
            seen.add(key)
            value = user_obj.get(key)
            if value:
                if line_number is not None:
                    return f"{line_number + 1}:{key}={value}"
                return f"{key}={value}"
        if line_number is not None:
            return f"{line_number + 1}:UNKNOWN"
        return "UNKNOWN"

    def _log_data_issue(
        self,
        user_obj: dict,
        line_number: int,
        message: str,
        context: object = "",
    ) -> None:
        logger.log(
            DATA_ISSUE_LVL_NUM,
            "DATA ISSUE\t%s\t%s\t%s",
            self._get_user_record_identifier(user_obj, line_number),
            message,
            self._serialize_data_issues_context(context),
        )

    def _log_record_failed(
        self,
        user_obj: dict,
        line_number: int,
        message: str,
        context: object = "",
    ) -> None:
        logger.log(
            DATA_ISSUE_LVL_NUM,
            "RECORD FAILED\t%s\t%s\t%s",
            self._get_user_record_identifier(user_obj, line_number),
            message,
            self._serialize_data_issues_context(context),
        )

    def _extract_error_details(self, exc: Exception) -> tuple[int | None, str, dict[str, Any]]:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        error_text = str(getattr(response, "text", str(exc)))
        payload = {}
        if response is not None:
            try:
                payload = response.json() or {}
            except (ValueError, TypeError):
                payload = {}
        if not payload and error_text:
            try:
                payload = json.loads(error_text)
            except (TypeError, ValueError):
                payload = {}
        return status_code, error_text, payload

    def _extract_folio_error_message(self, payload: dict[str, Any], fallback: str) -> str:
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict):
                    message = error.get("message")
                    if message:
                        return str(message)
        return fallback

    def _build_full_error_text(self, payload: dict[str, Any], error_text: str) -> str:
        return " ".join(
            [
                error_text,
                self._extract_folio_error_message(payload, ""),
                json.dumps(payload, ensure_ascii=False) if payload else "",
            ]
        ).lower()

    @staticmethod
    def _is_unique_conflict_error(full_error: str) -> bool:
        conflict_markers = [
            "already exists",
            "already assigned",
            "duplicate",
            "unique",
            "conflict",
            "violates unique",
            "not unique",
        ]
        return any(marker in full_error for marker in conflict_markers)

    def _get_unique_candidates(self, user_obj: dict) -> dict[str, str]:
        return {
            "username": user_obj.get("username", ""),
            "barcode": user_obj.get("barcode", ""),
            "externalSystemId": user_obj.get("externalSystemId", ""),
            "personal.email": self._get_nested_value(user_obj, "personal.email"),
        }

    @staticmethod
    def _find_conflict_matches_in_text(
        unique_candidates: dict[str, str],
        full_error: str,
    ) -> list[tuple[str, str]]:
        matches = []
        for field, value in unique_candidates.items():
            if not value:
                continue
            if field.lower() in full_error or str(value).lower() in full_error:
                matches.append((field, value))
        return matches

    @staticmethod
    def _extract_error_parameter_tokens(payload: dict[str, Any]) -> list[str]:
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        if not isinstance(errors, list):
            return []

        parameters = [
            parameter
            for error in errors
            if isinstance(error, dict)
            for parameter in error.get("parameters", [])
            if isinstance(parameter, dict)
        ]
        return [
            str(token).lower()
            for parameter in parameters
            for token in (parameter.get("key", ""), parameter.get("value", ""))
            if token
        ]

    @staticmethod
    def _is_candidate_in_error_tokens(field: str, value: str, tokens: list[str]) -> bool:
        if not value:
            return False
        field_lc = field.lower()
        value_lc = str(value).lower()
        return any(field_lc in token or value_lc in token for token in tokens)

    def _add_param_based_conflict_matches(
        self,
        matched: list[tuple[str, str]],
        unique_candidates: dict[str, str],
        payload: dict[str, Any],
    ) -> None:
        tokens = self._extract_error_parameter_tokens(payload)
        for field, value in unique_candidates.items():
            if (field, value) in matched:
                continue
            if self._is_candidate_in_error_tokens(field, value, tokens):
                matched.append((field, value))

    def _summarize_unique_conflict(
        self,
        user_obj: dict,
        payload: dict[str, Any],
        error_text: str,
    ) -> str | None:
        full_error = self._build_full_error_text(payload, error_text)
        if not self._is_unique_conflict_error(full_error):
            return None

        unique_candidates = self._get_unique_candidates(user_obj)
        matched = self._find_conflict_matches_in_text(unique_candidates, full_error)
        self._add_param_based_conflict_matches(matched, unique_candidates, payload)

        if matched:
            details = ", ".join([f'{field}="{value}"' for field, value in matched])
            return f"Unique field conflict in /users. Existing record already uses {details}."

        return (
            "Likely unique field conflict in /users. Check username, barcode, "
            "externalSystemId, and personal.email for duplicates."
        )

    def _build_record_failed_message(
        self,
        action: Literal["create", "update"],
        user_obj: dict,
        payload: dict[str, Any],
        error_text: str,
        status_code: int | None,
    ) -> str:
        unique_conflict_message = self._summarize_unique_conflict(
            user_obj,
            payload,
            error_text,
        )
        if unique_conflict_message:
            return f"User {action} failed. {unique_conflict_message}"

        status_hint = f" (HTTP {status_code})" if status_code else ""
        folio_message = self._extract_folio_error_message(payload, error_text)
        return f"User {action} failed{status_hint}: {folio_message}"

    async def setup(self, error_file_path: Path) -> None:
        """
        Sets up the importer by initializing necessary resources.

        Args:
            log_file_path (Path): The path to the log file.
            error_file_path (Path): The path to the error file.
        """
        self.errorfile = await aiofiles.open(error_file_path, "w", encoding="utf-8")

    async def close(self) -> None:
        """
        Closes the importer by releasing any resources.

        """
        if hasattr(self, "errorfile") and not self.errorfile.closed:
            await self.errorfile.close()

    async def do_import(self) -> None:
        """
        Main method to import users.

        This method triggers the process of importing users by calling the `process_file` method.
        Supports both single file path and list of file paths.
        """
        if not self.config.user_file_paths:
            raise FileNotFoundError("No user objects file provided")

        # Validate FolioClient async session availability before processing.
        _ = self.http_client

        # Normalize to list of paths
        file_paths = (
            [self.config.user_file_paths]
            if isinstance(self.config.user_file_paths, Path)
            else self.config.user_file_paths
        )

        # Process each file
        for idx, file_path in enumerate(file_paths, start=1):
            if len(file_paths) > 1:
                logger.info(f"Processing file {idx} of {len(file_paths)}: {file_path.name}")
            with open(file_path, "r", encoding="utf-8") as openfile:
                await self.process_file(openfile)

    async def get_existing_user(self, user_obj) -> dict:
        """
        Retrieves an existing user from FOLIO based on the provided user object.

        Args:
            user_obj: The user object containing the information to match against existing users.

        Returns:
            The existing user object if found, otherwise an empty dictionary.
        """
        match_key = "id" if ("id" in user_obj) else self.config.user_match_key
        try:
            existing_user = await self.http_client.get(
                "/users",
                headers=self.folio_client.okapi_headers,
                params={"query": f"{match_key}=={user_obj[match_key]}"},
            )
            existing_user.raise_for_status()
            existing_user = existing_user.json().get("users", [])
            existing_user = existing_user[0] if existing_user else {}
        except httpx.HTTPError:
            existing_user = {}
        return existing_user

    async def get_existing_rp(self, user_obj, existing_user) -> dict:
        """
        Retrieves the existing request preferences for a given user.

        Args:
            user_obj (dict): The user object.
            existing_user (dict): The existing user object.

        Returns:
            dict: The existing request preferences for the user.
        """
        try:
            existing_rp = await self.http_client.get(
                "/request-preference-storage/request-preference",
                headers=self.folio_client.okapi_headers,
                params={"query": f"userId=={existing_user.get('id', user_obj.get('id', ''))}"},
            )
            existing_rp.raise_for_status()
            existing_rp = existing_rp.json().get("requestPreferences", [])
            existing_rp = existing_rp[0] if existing_rp else {}
        except httpx.HTTPError:
            existing_rp = {}
        return existing_rp

    async def get_existing_pu(self, user_obj, existing_user) -> dict:
        """
        Retrieves the existing permission user for a given user.

        Args:
            user_obj (dict): The user object.
            existing_user (dict): The existing user object.

        Returns:
            dict: The existing permission user object.
        """
        existing_pu = {}
        if self.config.handle_permissions_user_objects and existing_user.get("id"):
            try:
                existing_pu = await self.http_client.get(
                    "/perms/users",
                    headers=self.folio_client.okapi_headers,
                    params={"query": f"userId=={existing_user.get('id', user_obj.get('id', ''))}"},
                )
                existing_pu.raise_for_status()
                existing_pu = existing_pu.json().get("permissionUsers", [])
                existing_pu = existing_pu[0] if existing_pu else {}
            except httpx.HTTPError:
                existing_pu = {}
        return existing_pu

    async def map_address_types(self, user_obj, line_number: int) -> None:
        """
        Maps address type names in the user object to the corresponding ID in the address_type_map.

        Args:
            user_obj (dict): The user object containing personal information.
            address_type_map (dict): A dictionary mapping address type names to their ID values.

        Returns:
            None

        Raises:
            KeyError: If an address type name in the user object is not found in address_type_map.

        """
        if "personal" in user_obj:
            addresses = user_obj["personal"].pop("addresses", [])
            mapped_addresses = []
            for address in addresses:
                try:
                    if (
                        self.validate_uuid(address["addressTypeId"])
                        and address["addressTypeId"] in self.address_type_map.values()
                    ):
                        logger.debug(
                            f"Row {line_number}: Address type {address['addressTypeId']} "
                            f"is a UUID, skipping mapping\n"
                        )
                        mapped_addresses.append(address)
                    else:
                        address["addressTypeId"] = self.address_type_map[address["addressTypeId"]]
                        mapped_addresses.append(address)
                except KeyError:
                    if address["addressTypeId"] not in self.address_type_map.values():
                        self._log_data_issue(
                            user_obj,
                            line_number,
                            (
                                "Address removed: addressTypeId "
                                f'"{address["addressTypeId"]}" could not be mapped.'
                            ),
                            {
                                "field": "personal.addresses[].addressTypeId",
                                "value": address.get("addressTypeId", ""),
                                "address": address,
                            },
                        )
                        logger.error(
                            f"Row {line_number}: Address type {address['addressTypeId']} not found"
                            f", removing address\n"
                        )
            if mapped_addresses:
                user_obj["personal"]["addresses"] = mapped_addresses

    async def map_patron_groups(self, user_obj, line_number: int) -> None:
        """
        Maps the patron group of a user object using the provided patron group map.

        Args:
            user_obj (dict): The user object to update.
            patron_group_map (dict): A dictionary mapping patron group names.

        Returns:
            None
        """
        try:
            if (
                self.validate_uuid(user_obj["patronGroup"])
                and user_obj["patronGroup"] in self.patron_group_map.values()
            ):
                logger.debug(
                    f"Row {line_number}: Patron group {user_obj['patronGroup']} is a UUID, "
                    f"skipping mapping\n"
                )
            else:
                user_obj["patronGroup"] = self.patron_group_map[user_obj["patronGroup"]]
        except KeyError:
            if user_obj["patronGroup"] not in self.patron_group_map.values():
                self._log_data_issue(
                    user_obj,
                    line_number,
                    f'Patron group removed: "{user_obj["patronGroup"]}" could not be mapped.',
                    {
                        "field": "patronGroup",
                        "value": user_obj.get("patronGroup", ""),
                    },
                )
                logger.error(
                    f"Row {line_number}: Patron group {user_obj['patronGroup']} not found in, "
                    f"removing patron group\n"
                )
                del user_obj["patronGroup"]

    async def map_departments(self, user_obj, line_number: int) -> None:
        """
        Maps the departments of a user object using the provided department map.

        Args:
            user_obj (dict): The user object to update.
            department_map (dict): A dictionary mapping department names.

        Returns:
            None
        """
        mapped_departments = []
        for department in user_obj.pop("departments", []):
            try:
                if self.validate_uuid(department) and department in self.department_map.values():
                    logger.debug(
                        f"Row {line_number}: Department {department} is a UUID, skipping mapping\n"
                    )
                    mapped_departments.append(department)
                else:
                    mapped_departments.append(self.department_map[department])
            except KeyError:
                self._log_data_issue(
                    user_obj,
                    line_number,
                    f'Department removed: "{department}" could not be mapped.',
                    {
                        "field": "departments[]",
                        "value": department,
                    },
                )
                logger.error(
                    f'Row {line_number}: Department "{department}" not found, '  # noqa: B907
                    f"excluding department from user\n"
                )
        if mapped_departments:
            user_obj["departments"] = mapped_departments

    async def update_existing_user(
        self, user_obj, existing_user, protected_fields
    ) -> Tuple[dict, httpx.Response]:
        """
        Updates an existing user with the provided user object.

        Args:
            user_obj (dict): The user object containing the updated user information.
            existing_user (dict): The existing user object to be updated.
            protected_fields (dict): A dictionary containing the protected fields and their values.

        Returns:
            tuple: A tuple containing the updated existing user object and the API response.

        Raises:
            None

        """

        await self.set_preferred_contact_type(user_obj, existing_user)
        preferred_contact_type = {
            "preferredContactTypeId": existing_user.get("personal", {}).pop(
                "preferredContactTypeId"
            )
        }
        if self.config.only_update_present_fields:
            new_personal = user_obj.pop("personal", {})
            existing_personal = existing_user.pop("personal", {})
            existing_preferred_first_name = existing_personal.pop("preferredFirstName", "")
            existing_addresses = existing_personal.get("addresses", [])
            existing_user.update(user_obj)
            existing_personal.update(new_personal)
            if (
                not existing_personal.get("preferredFirstName", "")
                and existing_preferred_first_name
            ):
                existing_personal["preferredFirstName"] = existing_preferred_first_name
            if not existing_personal.get("addresses", []):
                existing_personal["addresses"] = existing_addresses
            if existing_personal:
                existing_user["personal"] = existing_personal
        else:
            existing_user = {"id": existing_user["id"], **user_obj}
        if "personal" in existing_user:
            existing_user["personal"].update(preferred_contact_type)
        else:
            existing_user["personal"] = preferred_contact_type
        for key, value in protected_fields.items():
            if type(value) is dict:
                try:
                    existing_user[key].update(value)
                except KeyError:
                    existing_user[key] = value
            else:
                existing_user[key] = value
        create_update_user = await self.http_client.put(
            f"/users/{existing_user['id']}",
            headers=self.folio_client.okapi_headers,
            json=existing_user,
        )
        return existing_user, create_update_user

    async def create_new_user(self, user_obj) -> dict:
        """
        Creates a new user in the system.

        Args:
            user_obj (dict): A dictionary containing the user information.

        Returns:
            dict: A dictionary representing the response from the server.

        Raises:
            HTTPError: If the HTTP request to create the user fails.
        """
        # Normalize preferred contact type to numeric ID before create.
        await self.set_preferred_contact_type(user_obj, user_obj)
        response = await self.http_client.post(
            "/users",
            headers=self.folio_client.okapi_headers,
            json=user_obj,
        )
        response.raise_for_status()
        async with self.lock:
            self.stats.created += 1
        return response.json()

    async def set_preferred_contact_type(self, user_obj, existing_user) -> None:
        """
        Sets the preferred contact type for a user object. If the provided preferred contact type
        is not valid, the default preferred contact type is used, unless the previously existing
        user object has a valid preferred contact type set. In that case, the existing preferred
        contact type is used.
        """
        default_preferred_contact_type = self.normalize_preferred_contact_type(
            self.config.default_preferred_contact_type
        )
        if "personal" in user_obj and "preferredContactTypeId" in user_obj["personal"]:
            current_pref_contact = user_obj["personal"].get("preferredContactTypeId", "")
            if "personal" not in existing_user:
                existing_user["personal"] = {}
            existing_user["personal"]["preferredContactTypeId"] = (
                self.normalize_preferred_contact_type(current_pref_contact)
            )
        else:
            logger.warning(
                f"Preferred contact type not provided or is not a valid option: "
                f"{PREFERRED_CONTACT_TYPES_MAP} Setting preferred contact type to "
                f"{self.config.default_preferred_contact_type} or using existing value"
            )
            existing_contact_type = existing_user.get("personal", {}).get(
                "preferredContactTypeId", ""
            )
            if "personal" not in existing_user:
                existing_user["personal"] = {}
            existing_user["personal"]["preferredContactTypeId"] = (
                self.normalize_preferred_contact_type(existing_contact_type)
                if existing_contact_type
                else default_preferred_contact_type
            )

    def normalize_preferred_contact_type(self, preferred_contact_type: str) -> str:
        """Normalize preferred contact type names/IDs to a valid numeric ID."""
        if preferred_contact_type in PREFERRED_CONTACT_TYPES_MAP:
            return preferred_contact_type

        normalized_value = (preferred_contact_type or "").strip().lower()
        if mapped_contact_type := PREFERRED_CONTACT_TYPES_NAME_TO_ID.get(normalized_value):
            return mapped_contact_type

        default_preferred_contact_type = self.config.default_preferred_contact_type
        if default_preferred_contact_type in PREFERRED_CONTACT_TYPES_MAP:
            return default_preferred_contact_type

        return PREFERRED_CONTACT_TYPES_NAME_TO_ID.get(default_preferred_contact_type, "002")

    async def create_or_update_user(
        self, user_obj, existing_user, protected_fields, line_number: int
    ) -> dict:
        """
        Creates or updates a user based on the given user object and existing user.

        Args:
            user_obj (dict): The user object containing the user details.
            existing_user (dict): The existing user object to be updated, if available.
            logs (dict): A dictionary to keep track of the number of updates and failures.

        Returns:
            dict: The updated or created user object, or an empty dictionary an error occurs.
        """
        if existing_user:
            existing_user, update_user = await self.update_existing_user(
                user_obj, existing_user, protected_fields
            )
            try:
                update_user.raise_for_status()
                async with self.lock:
                    self.stats.updated += 1
                return existing_user
            except Exception as ee:
                status_code, error_text, payload = self._extract_error_details(ee)
                self._log_record_failed(
                    user_obj,
                    line_number,
                    self._build_record_failed_message(
                        "update", existing_user, payload, error_text, status_code
                    ),
                    {
                        "httpStatus": status_code,
                        "action": "update",
                        "folioError": self._extract_folio_error_message(payload, error_text),
                    },
                )
                logger.error(
                    f"Row {line_number}: User update failed: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )
                await self.errorfile.write(json.dumps(existing_user, ensure_ascii=False) + "\n")
                async with self.lock:
                    self.stats.failed += 1
                return {}
        else:
            try:
                new_user = await self.create_new_user(user_obj)
                return new_user
            except Exception as ee:
                status_code, error_text, payload = self._extract_error_details(ee)
                self._log_record_failed(
                    user_obj,
                    line_number,
                    self._build_record_failed_message(
                        "create", user_obj, payload, error_text, status_code
                    ),
                    {
                        "httpStatus": status_code,
                        "action": "create",
                        "folioError": self._extract_folio_error_message(payload, error_text),
                    },
                )
                logger.error(
                    f"Row {line_number}: User creation failed: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )
                await self.errorfile.write(json.dumps(user_obj, ensure_ascii=False) + "\n")
                async with self.lock:
                    self.stats.failed += 1
                return {}

    async def process_user_obj(self, user: str) -> dict:
        """
        Process a user object. If type is not found in the source object, type is set to "patron".

        Args:
            user (str): The user data to be processed, as a json string.

        Returns:
            dict: The processed user object.

        """
        user_obj = json.loads(user)
        user_obj["type"] = user_obj.get("type", "patron")
        return user_obj

    async def get_protected_fields(self, existing_user) -> dict:
        """
        Retrieves the protected fields from the existing user object,
        combining both the customFields.protectedFields list *and*
        any fields_to_protect passed on the CLI.

        Args:
            existing_user (dict): The existing user object.

        Returns:
            dict: A dictionary containing the protected fields and their values.
        """
        protected_fields = {}
        protected_fields_list = (
            existing_user.get("customFields", {}).get("protectedFields", "").split(",")
        )
        cli_fields = list(self.fields_to_protect)
        # combine and dedupe:
        all_fields = list(dict.fromkeys(protected_fields_list + cli_fields))
        for field in all_fields:
            if "." in field:
                fld, subfld = field.split(".", 1)
                val = existing_user.get(fld, {}).pop(subfld, None)
                if val is not None:
                    protected_fields.setdefault(fld, {})[subfld] = val
            else:
                val = existing_user.pop(field, None)
                if val is not None:
                    protected_fields[field] = val
        return protected_fields

    async def process_existing_user(
        self, user_obj
    ) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
        """
        Process an existing user.

        Args:
            user_obj (dict): The user object to process.

        Returns:
            tuple: A tuple containing the request preference object (rp_obj),
                   the service points user object (spu_obj),
                   the existing user object, the protected fields,
                   the existing request preference object (existing_rp),
                   the existing PU object (existing_pu),
                   and the existing SPU object (existing_spu).
        """
        rp_obj = user_obj.pop("requestPreference", {})
        spu_obj = user_obj.pop("servicePointsUser", {})
        existing_user = await self.get_existing_user(user_obj)
        if existing_user:
            existing_rp = await self.get_existing_rp(user_obj, existing_user)
            existing_pu = await self.get_existing_pu(user_obj, existing_user)
            existing_spu = await self.get_existing_spu(existing_user)
            protected_fields = await self.get_protected_fields(existing_user)
        else:
            existing_rp = {}
            existing_pu = {}
            existing_spu = {}
            protected_fields = {}
        return (
            rp_obj,
            spu_obj,
            existing_user,
            protected_fields,
            existing_rp,
            existing_pu,
            existing_spu,
        )

    async def create_or_update_rp(self, rp_obj, existing_rp, new_user_obj):
        """
        Creates or updates a requet preference object based on the given parameters.

        Args:
            rp_obj (object): A new requet preference object.
            existing_rp (object): The existing resource provider object, if it exists.
            new_user_obj (object): The new user object.

        Returns:
            None
        """
        if existing_rp:
            await self.update_existing_rp(rp_obj, existing_rp)
        else:
            await self.create_new_rp(new_user_obj)

    async def create_new_rp(self, new_user_obj):
        """
        Creates a new request preference for a user.

        Args:
            new_user_obj (dict): The user object containing the user's ID.

        Raises:
            HTTPError: If there is an error in the HTTP request.

        Returns:
            None
        """
        rp_obj = {"holdShelf": True, "delivery": False}
        rp_obj["userId"] = new_user_obj["id"]
        response = await self.http_client.post(
            "/request-preference-storage/request-preference",
            headers=self.folio_client.okapi_headers,
            json=rp_obj,
        )
        response.raise_for_status()

    async def update_existing_rp(self, rp_obj, existing_rp) -> None:
        """
        Updates an existing request preference with the provided request preference object.

        Args:
            rp_obj (dict): The request preference object containing the updated values.
            existing_rp (dict): The existing request preference object to be updated.

        Raises:
            HTTPError: If the PUT request to update the request preference fails.

        Returns:
            None
        """
        existing_rp.update(rp_obj)
        response = await self.http_client.put(
            self.folio_client.gateway_url
            + f"/request-preference-storage/request-preference/{existing_rp['id']}",
            headers=self.folio_client.okapi_headers,
            json=existing_rp,
        )
        response.raise_for_status()

    async def create_perms_user(self, new_user_obj) -> None:
        """
        Creates a permissions user object for the given new user.

        Args:
            new_user_obj (dict): A dictionary containing the details of the new user.

        Raises:
            HTTPError: If there is an error while making the HTTP request.

        Returns:
            None
        """
        if self.config.handle_permissions_user_objects is False:
            logger.debug(
                f"Skipping creation of permissions user for {new_user_obj['id']} "
                "as handle_permissions_user_objects is set to False\n"
            )
            return
        perms_user_obj = {"userId": new_user_obj["id"], "permissions": []}
        response = await self.http_client.post(
            "/perms/users",
            headers=self.folio_client.okapi_headers,
            json=perms_user_obj,
        )
        response.raise_for_status()

    async def delete_user(
        self, existing_user, existing_rp, existing_pu, existing_spu, line_number: int
    ) -> None:
        """
        Deletes a user and associated objects.

        Args:
            existing_user (dict): The existing user object to be deleted.
            existing_rp (dict): The existing request preference object associated with the user.
            existing_pu (dict): The existing permission user object associated with the user.
            existing_spu (dict): The existing service points user object associated with the user.
            line_number (int): The line number in the input file for logging purposes.
        Returns:
            None
        """
        if existing_user.get("type", "") in PROTECTED_USER_TYPES:
            logger.warning(
                f"Row {line_number}: User {existing_user['id']} "
                f"is of type {existing_user.get('type', '')}, "
                "skipping deletion\n"
            )
            return
        if existing_user:
            try:
                await self.folio_client.folio_delete_async(
                    f"/users/{existing_user['id']}",
                )
                logger.debug(f"Row {line_number}: Deleted user {existing_user['id']}\n")

                self.stats.deleted += 1
            except folioclient.FolioError as ee:
                logger.exception(
                    f"Row {line_number}: Failed to delete user {existing_user['id']}: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )
                self.stats.failed += 1
            try:
                if existing_rp:
                    await self.folio_client.folio_delete_async(
                        "/request-preference-storage/request-preference/"
                        f"{existing_rp.get('id', '')}"
                    )
            except folioclient.FolioError as ee:
                logger.exception(
                    f"Row {line_number}: Failed to delete request preference for user "
                    f"{existing_user['id']}: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )
            try:
                if existing_pu and self.delete_pus:
                    await self.folio_client.folio_delete_async(
                        f"/perms/users/{existing_pu.get('id', '')}"
                    )
            except folioclient.FolioError as ee:
                logger.exception(
                    f"Row {line_number}: Failed to delete permission user for user "
                    f"{existing_user['id']}: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )
            try:
                if existing_spu:
                    await self.folio_client.folio_delete_async(
                        f"/service-points-users/{existing_spu.get('id', '')}"
                    )
            except folioclient.FolioError as ee:
                logger.exception(
                    f"Row {line_number}: Failed to delete service points user for user "
                    f"{existing_user['id']}: "
                    f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}\n"
                )

    async def process_line(
        self,
        user: str,
        line_number: int,
    ) -> None:
        """
        Process a single line of user data.

        Args:
            user (str): The user data to be processed.
            logs (dict): A dictionary to store logs.

        Returns:
            None

        Raises:
            Any exceptions that occur during the processing.

        """
        async with self.limit_simultaneous_requests:
            user_obj = await self.process_user_obj(user)
            (
                rp_obj,
                spu_obj,
                existing_user,
                protected_fields,
                existing_rp,
                existing_pu,
                existing_spu,
            ) = await self.process_existing_user(user_obj)
            if self.config.delete_all:
                if existing_user:
                    await self.delete_user(
                        existing_user, existing_rp, existing_pu, existing_spu, line_number
                    )
                return
            await self.map_address_types(user_obj, line_number)
            await self.map_patron_groups(user_obj, line_number)
            await self.map_departments(user_obj, line_number)
            new_user_obj = await self.create_or_update_user(
                user_obj, existing_user, protected_fields, line_number
            )
            if new_user_obj:
                try:
                    if existing_rp or rp_obj:
                        await self.create_or_update_rp(rp_obj, existing_rp, new_user_obj)
                    else:
                        logger.debug(
                            f"Row {line_number}: Creating default request preference object"
                            f" for {new_user_obj['id']}\n"
                        )
                        await self.create_new_rp(new_user_obj)
                except Exception as ee:  # noqa: W0718
                    rp_error_message = (
                        f"Row {line_number}: Error creating or updating request preferences for "
                        f"{new_user_obj['id']}: "
                        f"{str(getattr(getattr(ee, 'response', ee), 'text', str(ee)))}"
                    )
                    logger.error(rp_error_message)
                if not existing_pu:
                    try:
                        await self.create_perms_user(new_user_obj)
                    except Exception as ee:  # noqa: W0718
                        pu_error_message = (
                            f"Row {line_number}: Error creating permissionUser object for user: "
                            f"{new_user_obj['id']}: "
                            f"{str(getattr(getattr(ee, 'response', str(ee)), 'text', str(ee)))}"
                        )
                        logger.error(pu_error_message)
                await self.handle_service_points_user(
                    spu_obj, existing_spu, new_user_obj, line_number
                )

    async def map_service_points(self, spu_obj, existing_user, line_number: int):
        """
        Maps the service points of a user object using the provided service point map.

        Args:
            spu_obj (dict): The service-points-user object to update.
            existing_user (dict): The existing user object associated with the spu_obj.

        Returns:
            None
        """
        if "servicePointsIds" in spu_obj:
            mapped_service_points = []
            for sp in spu_obj.pop("servicePointsIds", []):
                try:
                    if self.validate_uuid(sp) and sp in self.service_point_map.values():
                        logger.debug(f"Service point {sp} is a UUID, skipping mapping\n")
                        mapped_service_points.append(sp)
                    else:
                        mapped_service_points.append(self.service_point_map[sp])
                except KeyError:
                    self._log_data_issue(
                        existing_user,
                        line_number,
                        f'Service point removed: "{sp}" could not be mapped.',
                        {
                            "field": "servicePointsUser.servicePointsIds[]",
                            "value": sp,
                        },
                    )
                    logger.error(
                        f'Service point "{sp}" not found, excluding service point from user: '
                        f"{self.service_point_map}"
                    )
            if mapped_service_points:
                spu_obj["servicePointsIds"] = mapped_service_points
        if "defaultServicePointId" in spu_obj:
            sp_code = spu_obj.pop("defaultServicePointId", "")
            try:
                if self.validate_uuid(sp_code) and sp_code in self.service_point_map.values():
                    logger.debug(f"Default service point {sp_code} is a UUID, skipping mapping\n")
                    mapped_sp_id = sp_code
                else:
                    mapped_sp_id = self.service_point_map[sp_code]
                if mapped_sp_id not in spu_obj.get("servicePointsIds", []):
                    self._log_data_issue(
                        existing_user,
                        line_number,
                        (
                            f'Default service point "{sp_code}" removed because it is not '
                            "present in servicePointsIds."
                        ),
                        {
                            "field": "servicePointsUser.defaultServicePointId",
                            "value": sp_code,
                        },
                    )
                    logger.warning(
                        f'Default service point "{sp_code}" not found in assigned service points, '
                        "excluding default service point from user"
                    )
                else:
                    spu_obj["defaultServicePointId"] = mapped_sp_id
            except KeyError:
                self._log_data_issue(
                    existing_user,
                    line_number,
                    f'Default service point removed: "{sp_code}" could not be mapped.',
                    {
                        "field": "servicePointsUser.defaultServicePointId",
                        "value": sp_code,
                    },
                )
                logger.error(
                    f'Default service point "{sp_code}" not found, excluding default service '
                    f"point from user: {existing_user['id']}"
                )

    async def handle_service_points_user(self, spu_obj, existing_spu, existing_user, line_number):
        """
        Handles processing a service-points-user object for a user.

        Args:
            spu_obj (dict): The service-points-user object to process.
            existing_spu (dict): The existing service-points-user object, if it exists.
            existing_user (dict): The existing user object associated with the spu_obj.
        """
        if spu_obj:
            await self.map_service_points(spu_obj, existing_user, line_number)
            if existing_spu:
                await self.update_existing_spu(spu_obj, existing_spu)
            else:
                await self.create_new_spu(spu_obj, existing_user)

    async def get_existing_spu(self, existing_user):
        """
        Retrieves the existing service-points-user object for a given user.

        Args:
            existing_user (dict): The existing user object.

        Returns:
            dict: The existing service-points-user object.
        """
        try:
            existing_spu = await self.http_client.get(
                "/service-points-users",
                headers=self.folio_client.okapi_headers,
                params={"query": f"userId=={existing_user['id']}"},
            )
            existing_spu.raise_for_status()
            existing_spu = existing_spu.json().get("servicePointsUsers", [])
            existing_spu = existing_spu[0] if existing_spu else {}
        except httpx.HTTPError:
            existing_spu = {}
        return existing_spu

    async def create_new_spu(self, spu_obj, existing_user):
        """
        Creates a new service-points-user object for a given user.

        Args:
            spu_obj (dict): The service-points-user object to create.
            existing_user (dict): The existing user object.

        Returns:
            None
        """
        spu_obj["userId"] = existing_user["id"]
        response = await self.http_client.post(
            "/service-points-users",
            headers=self.folio_client.okapi_headers,
            json=spu_obj,
        )
        response.raise_for_status()

    async def update_existing_spu(self, spu_obj, existing_spu):
        """
        Updates an existing service-points-user object with the provided service-points-user object.

        Args:
            spu_obj (dict): The service-points-user object containing the updated values.
            existing_spu (dict): The existing service-points-user object to be updated.

        Returns:
            None
        """  # noqa: E501
        existing_spu.update(spu_obj)
        response = await self.http_client.put(
            f"/service-points-users/{existing_spu['id']}",
            headers=self.folio_client.okapi_headers,
            json=existing_spu,
        )
        response.raise_for_status()

    async def process_file(self, openfile: TextIOWrapper) -> None:
        """
        Process the user object file.

        Args:
            openfile: The file or file-like object to process.
        """
        with open(openfile.name, "rb") as f:
            total_lines = sum(buf.count(b"\n") for buf in iter(lambda: f.read(1024 * 1024), b""))

        with self.reporter:
            description = "Deleting users" if self.config.delete_all else "Importing users"
            task_id = self.reporter.start_task(
                "users",
                total=total_lines,
                description=description,
            )
            openfile.seek(0)
            tasks = []
            for line_number, user in enumerate(openfile):
                tasks.append(self.process_line(user, line_number))
                if len(tasks) == self.config.batch_size:
                    start = time.time()
                    await asyncio.gather(*tasks)
                    duration = time.time() - start
                    async with self.lock:
                        if self.config.delete_all:
                            self.reporter.update_task(
                                task_id,
                                advance=len(tasks),
                                deleted=self.stats.deleted,
                                failed=self.stats.failed,
                            )
                            message = (
                                f"{dt.now().isoformat(sep=' ', timespec='milliseconds')}: "
                                f"Batch of {self.config.batch_size} users processed in "
                                f"{duration:.2f} seconds. - Users deleted: {self.stats.deleted}"
                                f" - Users failed: {self.stats.failed}"
                            )
                        else:
                            self.reporter.update_task(
                                task_id,
                                advance=len(tasks),
                                created=self.stats.created,
                                updated=self.stats.updated,
                                failed=self.stats.failed,
                            )
                            message = (
                                f"{dt.now().isoformat(sep=' ', timespec='milliseconds')}: "
                                f"Batch of {self.config.batch_size} users processed in "
                                f"{duration:.2f} seconds. - Users created: {self.stats.created}"
                                f" - Users updated: {self.stats.updated} - Users failed: "
                                f"{self.stats.failed}"
                            )
                        logger.info(message)
                    tasks = []
            if tasks:
                start = time.time()
                await asyncio.gather(*tasks)
                duration = time.time() - start
                async with self.lock:
                    if self.config.delete_all:
                        self.reporter.update_task(
                            task_id,
                            advance=len(tasks),
                            deleted=self.stats.deleted,
                            failed=self.stats.failed,
                        )
                        message = (
                            f"{dt.now().isoformat(sep=' ', timespec='milliseconds')}: "
                            f"Batch of {len(tasks)} users processed in {duration:.2f} seconds. - "
                            f"Users deleted: {self.stats.deleted}"
                            f" - Users failed: {self.stats.failed}"
                        )
                    else:
                        self.reporter.update_task(
                            task_id,
                            advance=len(tasks),
                            created=self.stats.created,
                            updated=self.stats.updated,
                            failed=self.stats.failed,
                        )
                        message = (
                            f"{dt.now().isoformat(sep=' ', timespec='milliseconds')}: "
                            f"Batch of {len(tasks)} users processed in {duration:.2f} seconds. - "
                            f"Users created: {self.stats.created} - Users updated: "
                            f"{self.stats.updated} - Users failed: {self.stats.failed}"
                        )
                    logger.info(message)

    def get_stats(self) -> UserImporterStats:
        """
        Get current import statistics.

        Returns:
            Current statistics
        """
        return self.stats


app = cyclopts.App()


@app.default
def main(
    config_file: Annotated[
        Path | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
    *,
    gateway_url: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_GATEWAY_URL", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_TENANT_ID", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    username: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_USERNAME", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    password: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_PASSWORD", show_env_var=True, group="FOLIO Connection Parameters"
        ),
    ] = None,
    library_name: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_LIBRARY_NAME", show_env_var=True, group="Job Configuration Parameters"
        ),
    ] = None,
    user_file_paths: Annotated[
        Tuple[Path, ...] | None,
        cyclopts.Parameter(
            name=["--user-file-paths", "--user-file-path"],
            help=(
                "Path(s) to user data file(s). "
                "Accepts multiple values. Can be used as --user-file-paths or --user-file-path."
            ),
            group="Job Configuration Parameters",
        ),
    ] = None,
    member_tenant_id: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_MEMBER_TENANT_ID",
            show_env_var=True,
            group="FOLIO Connection Parameters",
        ),
    ] = None,
    delete_all: Annotated[
        bool,
        cyclopts.Parameter(
            env_var="FOLIO_DELETE_ALL_USERS",
            show_env_var=True,
            group="Job Configuration Parameters",
        ),
    ] = False,
    fields_to_protect: Annotated[
        str | None,
        cyclopts.Parameter(
            env_var="FOLIO_FIELDS_TO_PROTECT",
            show_env_var=True,
            group="Job Configuration Parameters",
        ),
    ] = None,
    update_only_present_fields: Annotated[
        bool, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = False,
    limit_async_requests: Annotated[
        int,
        cyclopts.Parameter(
            env_var="FOLIO_LIMIT_ASYNC_REQUESTS",
            show_env_var=True,
            group="Job Configuration Parameters",
        ),
    ] = 10,
    batch_size: Annotated[
        int,
        cyclopts.Parameter(
            env_var="FOLIO_USER_IMPORT_BATCH_SIZE",
            show_env_var=True,
            group="Job Configuration Parameters",
        ),
    ] = 250,
    report_file_base_path: Annotated[
        Path | None, cyclopts.Parameter(group="Job Configuration Parameters")
    ] = None,
    user_match_key: Annotated[
        Literal["externalSystemId", "username", "barcode"],
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = "externalSystemId",
    default_preferred_contact_type: Annotated[
        Literal["001", "002", "003", "004", "005", "mail", "email", "text", "phone", "mobile"],
        cyclopts.Parameter(group="Job Configuration Parameters"),
    ] = "email",
    no_progress: Annotated[bool, cyclopts.Parameter(group="Job Configuration Parameters")] = False,
    yes: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--yes", "-y"],
            group="Job Configuration Parameters",
            help="Skip confirmation prompt for destructive operations (e.g. --delete-all).",
        ),
    ] = False,
    debug: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--debug"], group="General Parameters", help="Enable debug logging"
        ),
    ] = False,
) -> None:
    """
    Command-line interface to batch import users into FOLIO

    Parameters:
        config_file (Path | None): Path to a JSON configuration file. Overrides job configuration parameters if provided.
        gateway_url (str): The FOLIO gateway URL.
        tenant_id (str): The FOLIO tenant ID.
        username (str): The FOLIO username.
        password (str): The FOLIO password.
        library_name (str): The library name associated with the job.
        user_file_paths (Tuple[Path, ...]): Path(s) to the user data file(s). Use
            --user-file-paths or --user-file-path (deprecated, will be removed in future versions).
        member_tenant_id (str): The FOLIO ECS member tenant id (if applicable).
        delete_all (bool): Whether to delete existing users, rather than create/update.
        fields_to_protect (str): Comma-separated list of fields to protect during update.
        update_only_present_fields (bool): Whether to update only fields present in the input.
        limit_async_requests (int): The maximum number of concurrent async HTTP requests.
        batch_size (int): The number of users to process in each batch.
        report_file_base_path (Path): The base path for report files.
        user_match_key (str): The key to match users (externalSystemId, username, barcode).
        default_preferred_contact_type (str): The default preferred contact type for users
        no_progress (bool): Whether to disable the progress bar.
        yes (bool): Skip confirmation prompt for destructive operations (e.g. --delete-all).
        debug (bool): Enable debug logging.
    """  # noqa: E501
    set_up_cli_logging(logger, "folio_user_import", debug, True, stream_level=logging.WARNING)
    fields_to_protect = fields_to_protect or ""
    protect_fields = [f.strip() for f in fields_to_protect.split(",") if f.strip()]

    gateway_url, tenant_id, username, password = get_folio_connection_parameters(
        gateway_url, tenant_id, username, password
    )
    folio_client = folioclient.FolioClient(gateway_url, tenant_id, username, password)

    # Set the member tenant id if provided to support FOLIO ECS multi-tenant environments
    if member_tenant_id:
        folio_client.tenant_id = member_tenant_id

    report_file_base_path = report_file_base_path or Path.cwd()
    error_file_path = (
        report_file_base_path / f"failed_user_import_{dt.now(utc).strftime('%Y%m%d_%H%M%S')}.txt"
    )

    if delete_all:
        logger.warning(
            "--delete-all flag is set. Users present in the provided file(s) will be "
            "deleted rather than created or updated. Proceed with caution."
        )
        if not yes:
            if not sys.stdin.isatty():
                logger.critical("--delete-all requires --yes/-y flag in non-interactive mode.")
                sys.exit(1)
            input("Press Enter to proceed with deletions, or Ctrl+C to abort...")

    config_data = {}
    if config_file:
        try:
            with open(config_file, "r") as f:
                config_data = json.load(f)
                # CLI flags override config file values
                config_data["delete_all"] = delete_all
                config = UserImporter.Config(**config_data)
        except Exception as e:
            logger.critical(f"Failed to load configuration file {config_file}: {e}")
            sys.exit(1)
    else:
        # Expand any glob patterns in file paths
        expanded_paths = pathify_user_file_paths(user_file_paths)

        # Convert to single Path or List[Path] for Config
        file_paths_list = expanded_paths if len(expanded_paths) > 1 else expanded_paths[0]

        config = UserImporter.Config(
            library_name=library_name,
            batch_size=batch_size,
            user_match_key=user_match_key,
            only_update_present_fields=update_only_present_fields,
            default_preferred_contact_type=default_preferred_contact_type,
            fields_to_protect=protect_fields,
            limit_simultaneous_requests=limit_async_requests,
            user_file_paths=file_paths_list,
            no_progress=no_progress,
            delete_all=delete_all,
        )
    try:
        importer = UserImporter(folio_client, config)
        asyncio.run(run_user_importer(importer, error_file_path))
    except Exception as ee:
        logger.critical(f"An unknown error occurred: {ee}")
        sys.exit(1)


def pathify_user_file_paths(user_file_paths):
    expanded_paths = []
    for path_arg in user_file_paths:
        path_str = str(path_arg)
        # Check if it contains glob wildcards
        if any(char in path_str for char in ["*", "?", "["]):
            # Expand the glob pattern
            matches = glob.glob(path_str)
            if matches:
                expanded_paths.extend([Path(p) for p in sorted(matches)])
            else:
                # No matches - treat as literal path (will error later if file doesn't exist)
                expanded_paths.append(path_arg)
        else:
            expanded_paths.append(path_arg)
    return expanded_paths


async def run_user_importer(importer: UserImporter, error_file_path: Path):
    try:
        async with importer.folio_client:
            await importer.setup(error_file_path)
            await importer.do_import()
    except Exception as ee:
        logger.critical(f"An unknown error occurred: {ee}")
        sys.exit(1)
    finally:
        await importer.close()


# Run the main function
if __name__ == "__main__":
    app()
