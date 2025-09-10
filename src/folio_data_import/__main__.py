import typer

from folio_data_import.MARCDataImport import main as marc_app
from folio_data_import.UserImport import main as users_main

app = typer.Typer()

app.command(name="marc")(marc_app)
app.command(name="users")(users_main)

if __name__ == "__main__":
    app()
