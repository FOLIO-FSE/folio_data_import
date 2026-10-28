# Required Permissions and Capabilities

Every FOLIO API call made by this tool is authorized against the user account you log in with. This page lists what that account needs for each subcommand.

- **Okapi (non-Eureka) systems** use *permissions*, listed below by their permission name (e.g. `users.item.post`). Add them to a permission set assigned to the user.
- **Eureka systems** use *capabilities*, listed below by capability name (e.g. `users_item.create`). Add them to a role assigned to the user.

```{note}
The permission names were taken from the module descriptors of the FOLIO modules that serve each endpoint (`mod-users`, `mod-permissions`, `mod-inventory-storage`, `mod-circulation-storage`, `mod-source-record-manager`, `mod-data-import-converter-storage`, `mod-users-bl`, and for module versions Okapi itself, `mod-okapi-facade` and `mgr-tenant-entitlements`). Capability names are derived from permission names by the same rules FOLIO uses to generate capabilities (`folio-permission-utils`): dots become underscores, the name is lowercased, and the final segment becomes the action (`get` → `view`, `post` → `create`, `put` → `edit`, `delete` → `delete`). A `post` permission that does not end in `.item.post` or `.collection.post` (e.g. the batch and change-manager permissions) is procedural, and its action is `execute`. A few permissions (e.g. `okapi.proxy.tenants.modules.list`, whose final segment `list` has no automatic action) get their capability from the explicit mappings in `folio-permissions-mappings` instead. Module versions differ, so if a capability is not found in your tenant, search your role editor for the resource name (e.g. "Users Item").
```

Each table lists the endpoint, the permission name and its display name in the Okapi permission-set editor, and the capability name and the resource and action as shown in the Eureka role editor. The rows marked *conditional* are only needed when the corresponding option or data is in use.

## All subcommands: login

Logging in (`/authn/login-with-expiry`) requires no permissions. The `marc` command also looks up the current user's ID (to create the job execution); this tries `/bl-users/by-username/{username}` first (permission `users-bl.users-by-username.item.get`, UI name "users-bl item get by username", capability `users-bl_users-by-username_item.view`, Eureka UI "Users-Bl Users-By-Username Item — View") and falls back to `/users` (`users.collection.get`, "users collection get" / `users_collection.view`, "Users Collection — View"). In ECS environments, this lookup is made in the tenant you log in to, not the member tenant, so the permission is needed there.

On construction, the client also checks whether the tenant is an ECS central tenant by calling `GET /consortia` and `GET /consortia/{id}/tenants`. The `mod-consortia` module descriptor declares no required permissions for these endpoints, and the client treats any HTTP error as "not ECS", so nothing needs to be granted for this check. Expired tokens are renewed by logging in again, which also needs no permissions.

## `folio-data-import marc` (MARC Data Import)

| Purpose | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| List job profiles | `GET /data-import-profiles/jobProfiles` | `converter-storage.jobprofile.get` | Data Import Converter Storage - get Job Profile(s) | `converter-storage_jobprofile.view` | Converter-Storage Jobprofile — View |
| Create job execution | `POST /change-manager/jobExecutions` | `change-manager.jobexecutions.post` | Change Manager - create jobExecutions | `change-manager_jobexecutions.execute` | Change-Manager Jobexecutions — Execute |
| Read job execution | `GET /change-manager/jobExecutions/{id}` | `change-manager.jobExecutions.item.get` | Change Manager - get jobExecutions by id | `change-manager_jobexecutions_item.view` | Change-Manager JobExecutions Item — View |
| Set file name | `PUT /change-manager/jobExecutions/{id}` | `change-manager.jobExecutions.item.put` | Change Manager - update jobExecution | `change-manager_jobexecutions_item.edit` | Change-Manager JobExecutions Item — Edit |
| Set job profile | `PUT /change-manager/jobExecutions/{id}/jobProfile` | `change-manager.jobExecutions.jobProfile.item.put` | Change Manager - set jobProfile for jobExecution | `change-manager_jobexecutions_jobprofile_item.edit` | Change-Manager JobExecutions JobProfile Item — Edit |
| Upload records | `POST /change-manager/jobExecutions/{id}/records` | `change-manager.records.post` | Change Manager - post chunk of raw records | `change-manager_records.execute` | Change-Manager Records — Execute |
| Poll job status | `GET /metadata-provider/jobExecutions` | `metadata-provider.jobExecutions.collection.get` | Metadata Provider - get jobExecutions | `metadata-provider_jobexecutions_collection.view` | Metadata-Provider JobExecutions Collection — View |
| Job summary | `GET /metadata-provider/jobSummary/{id}` | `metadata-provider.jobSummary.item.get` | Metadata Provider - get summary result | `metadata-provider_jobsummary_item.view` | Metadata-Provider JobSummary Item — View |

Conditional:

| When | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| Cancelling a job after an upload error | `DELETE /change-manager/jobExecutions/{id}/records` | `change-manager.records.delete` | Change Manager - delete jobExecution and all associated records from SRS | `change-manager_records.delete` | Change-Manager Records — Delete |

The records the job profile creates or updates (instances, holdings, items, authorities, etc.) are written by FOLIO's own modules, not by this account.

## `folio-data-import users` (User Import)

| Purpose | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| Look up existing users | `GET /users` | `users.collection.get` | users collection get | `users_collection.view` | Users Collection — View |
| Create user | `POST /users` | `users.item.post` | users item post | `users_item.create` | Users Item — Create |
| Update user | `PUT /users/{id}` | `users.item.put` | users item put | `users_item.edit` | Users Item — Edit |
| Patron groups | `GET /groups` | `usergroups.collection.get` | usergroups collection get | `usergroups_collection.view` | Usergroups Collection — View |
| Address types | `GET /addresstypes` | `addresstypes.collection.get` | addresstypes collection get | `addresstypes_collection.view` | Addresstypes Collection — View |
| Departments | `GET /departments` | `departments.collection.get` | departments collection get | `departments_collection.view` | Departments Collection — View |
| Service points (for lookup) | `GET /service-points` | `inventory-storage.service-points.collection.get` | inventory storage - get service-point collection | `inventory-storage_service-points_collection.view` | Inventory-Storage Service-Points Collection — View |
| Module versions (used to find the `mod-users` module id) | `GET /_/proxy/tenants/{tenant}/modules` (served by `mod-okapi-facade` in Eureka). If this fails, `folioclient` falls back to `GET /entitlements/{tenant}/applications` (`mgr-tenant-entitlements`, no permissions declared) | `okapi.proxy.tenants.modules.list` | Okapi - List modules enabled for tenant | `okapi_proxy_tenants_modules_list.view` | Okapi Proxy Tenants Modules List |
| Custom fields (served by `mod-users`; sent with an `X-Okapi-Module-Id` header) | `GET /custom-fields` | `user-settings.custom-fields.collection.get` | User Custom Fields - get collection | `user-settings_custom-fields_collection.view` | User-Settings Custom-Fields Collection — View |
| Request preference lookup | `GET /request-preference-storage/request-preference` | `circulation-storage.request-preferences.collection.get` | Circulation storage - get request preference collection | `circulation-storage_request-preferences_collection.view` | Circulation-Storage Request-Preferences Collection — View |
| Create request preference | `POST /request-preference-storage/request-preference` | `circulation-storage.request-preferences.item.post` | Circulation storage - post individual request preference | `circulation-storage_request-preferences_item.create` | Circulation-Storage Request-Preferences Item — Create |
| Service-points user lookup (made for every existing user) | `GET /service-points-users` | `inventory-storage.service-points-users.collection.get` | inventory storage - get service-point-users collection | `inventory-storage_service-points-users_collection.view` | Inventory-Storage Service-Points-Users Collection — View |
| Update request preference (existing users who already have one, even if the file has no `requestPreference`) | `PUT /request-preference-storage/request-preference/{id}` | `circulation-storage.request-preferences.item.put` | Circulation storage - put individual request preference | `circulation-storage_request-preferences_item.edit` | Circulation-Storage Request-Preferences Item — Edit |

Conditional on options and data:

| When | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| Permissions user objects are handled (default; disabled by `--ignore-permissions-user-objects`) | `GET /perms/users` | `perms.users.get` | permission users read | `perms_users.view` | Perms Users — View |
|  | `POST /perms/users` | `perms.users.item.post` | permission users item create | `perms_users_item.create` | Perms Users Item — Create |
| Service points are assigned to users | `POST /service-points-users` | `inventory-storage.service-points-users.item.post` | inventory storage - create individual service-points-user | `inventory-storage_service-points-users_item.create` | Inventory-Storage Service-Points-Users Item — Create |
|  | `PUT /service-points-users/{id}` | `inventory-storage.service-points-users.item.put` | inventory storage - modify service-points-user | `inventory-storage_service-points-users_item.edit` | Inventory-Storage Service-Points-Users Item — Edit |
| Deleting users (`--delete-all`) | `DELETE /users/{id}` | `users.item.delete` | users item delete | `users_item.delete` | Users Item — Delete |
|  | `DELETE /request-preference-storage/request-preference/{id}` | `circulation-storage.request-preferences.item.delete` | Circulation storage - delete request preference | `circulation-storage_request-preferences_item.delete` | Circulation-Storage Request-Preferences Item — Delete |
|  | `DELETE /perms/users/{id}` (permissions user objects handled and `delete_pus: true` in the config file) | `perms.users.item.id.delete` | permission user delete | `perms_users_item_id.delete` | Perms Users Item Id — Delete |
|  | `DELETE /service-points-users/{id}` | `inventory-storage.service-points-users.item.delete` | inventory storage - delete individual service-points-user | `inventory-storage_service-points-users_item.delete` | Inventory-Storage Service-Points-Users Item — Delete |

```{note}
The module-version and custom-field lookups are only used to resolve select-type custom field labels to option ids. If either fails (for example a missing permission), the import logs a warning and continues, and custom field values must then be supplied as option ids.
```

```{warning}
A missing *read* permission for an existing-record lookup (users, request preferences, permissions users, service-points users) does not stop the import. The failed lookup is treated as "no existing record", so the tool tries to create a record instead of updating it. Those errors look like duplicate-record failures, not permission errors.
```

## `folio-data-import batch-poster` (Batch Poster)

Posting needs the batch permission for the record type. Reading existing records is only needed in upsert mode (`--upsert`) and patch mode, which fetch the current records before posting.

| Record type | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| `Items` | `POST /item-storage/batch/synchronous` | `inventory-storage.items.batch.post` | inventory storage - create or update a number of items | `inventory-storage_items_batch.execute` | Inventory-Storage Items Batch — Execute |
| `Holdings` | `POST /holdings-storage/batch/synchronous` | `inventory-storage.holdings.batch.post` | inventory storage - create or update a number of holdings | `inventory-storage_holdings_batch.execute` | Inventory-Storage Holdings Batch — Execute |
| `Instances`, `ShadowInstances` | `POST /instance-storage/batch/synchronous` | `inventory-storage.instances.batch.synchronous.post` | inventory storage - create or update a collection of instances in a single synchronous request | `inventory-storage_instances_batch_synchronous.execute` | Inventory-Storage Instances Batch Synchronous — Execute |

Conditional on `--upsert` / patching:

| Record type | Endpoint | Permission (Okapi) | Okapi UI display name | Capability (Eureka) | Eureka UI resource — action |
|---|---|---|---|---|---|
| `Items` | `GET /item-storage/items` | `inventory-storage.items.collection.get` | inventory storage - get item collection | `inventory-storage_items_collection.view` | Inventory-Storage Items Collection — View |
| `Holdings` | `GET /holdings-storage/holdings` | `inventory-storage.holdings.collection.get` | inventory storage - get holdings collection | `inventory-storage_holdings_collection.view` | Inventory-Storage Holdings Collection — View |
| `Instances`, `ShadowInstances` | `GET /instance-storage/instances` | `inventory-storage.instances.collection.get` | inventory storage - get instance collection | `inventory-storage_instances_collection.view` | Inventory-Storage Instances Collection — View |

In ECS environments, the account needs these in the tenant given by `--member-tenant-id` (for `ShadowInstances`, the member tenant that receives the shadow copies).

## `folio-data-import get-di-logs` (Data Import Log Retriever)

This command does **not** call the data-import APIs for log content: it reads Data Import journal and incoming-record data directly from the FOLIO PostgreSQL database (direct PostgreSQL access required). No FOLIO API permissions beyond a successful login are needed. The *database* user needs `SELECT` on:

- `{tenant}_mod_source_record_manager.journal_records`
- `{tenant}_mod_source_record_manager.incoming_records`

See [Data Import Log Retriever Guide](di_log_retriever_guide.md) for connection options.
