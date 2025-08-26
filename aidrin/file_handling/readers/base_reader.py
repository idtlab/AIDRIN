"""
Use the 'BaseFileReader' template and examples
below to add your own file parsing logic.

"""


class BaseFileReader:
    def __init__(self, file_path: str, logger):
        self.file_path = file_path
        self.logger = logger

    def read(self):
        raise NotImplementedError("Subclasses must implement the read() method.")

    # Optional method: parse hierarchical group identifiers
    def parse(self):
        return None

    # Optional method: filter by keys for hierarchical data
    def filter(self, kept_keys):
        return None
