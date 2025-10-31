import cyclopts

app = cyclopts.App(default_parameter=cyclopts.Parameter(negative=()))
app.register_install_completion_command()

# Using string-based import paths for commands as required by cyclopts to support dynamic loading.
app.command("folio_data_import.MARCDataImport:main", name="marc")
app.command("folio_data_import.UserImport:main", name="users")

if __name__ == "__main__":
    app()
