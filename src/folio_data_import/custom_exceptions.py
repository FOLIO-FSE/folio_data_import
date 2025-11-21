"""Custom exceptions for the Folio Data Import module."""


class FolioDataImportError(Exception):
    """Base class for all exceptions in the Folio Data Import module."""

    pass


class FolioDataImportBatchError(FolioDataImportError):
    """Exception raised for errors in the Folio Data Import batch process.

    Attributes:
        batch_id -- ID of the batch that caused the error
        message -- explanation of the error
    """

    def __init__(self, batch_id, message, exception=None) -> None:
        self.batch_id = batch_id
        self.message = message
        super().__init__(f"Unhandled error posting batch {batch_id}: {message}")


class FolioDataImportJobError(FolioDataImportError):
    """Exception raised for errors in the Folio Data Import job process.

    Attributes:
        job_id -- ID of the job that caused the error
        message -- explanation of the error
    """

    def __init__(self, job_id, message, exception=None) -> None:
        self.job_id = job_id
        self.message = message
        super().__init__(f"Unhandled error processing job {job_id}: {message}")
