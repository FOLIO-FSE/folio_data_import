import cyclopts

app = cyclopts.App(default_parameter=cyclopts.Parameter(negative=()))

app.command("folio_data_import.MARCDataImport:main", name="marc")
app.command("folio_data_import.UserImport:main", name="users")

if __name__ == "__main__":
    app()
