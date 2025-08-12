import json
import os
import uuid

import pandas as pd
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


class jsonReader(BaseFileReader):
    def read(self):
        # flatten data recursively (either dict or list)
        def flatten_json(data):
            rows = []
            # recursively parse data to find low level lists

            def recurse(obj, path=[]):
                if isinstance(obj, dict):
                    for key, val in obj.items():
                        recurse(val, path + [key])
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            row = item.copy()
                            rows.append(row)

            recurse(data)
            return pd.DataFrame(rows)

        with open(self.file_path) as f:
            data = json.load(f)
        df = flatten_json(data)
        return df

    def parse(self):
        with open(self.file_path) as f:
            data = json.load(f)
            # only parse hierarchical data
            if isinstance(data, dict):
                self.logger.info("Keys found: %s", data.keys())
                return list(data.keys())

    def filter(self, kept_keys):
        with open(self.file_path) as f:
            data = json.load(f)
        # fix str passing
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(",")
        # Only keep keys the user selected
        filtered_data = {k: data[k] for k in kept_keys if k in data}

        new_file_name = (
            f"filtered_{uuid.uuid4().hex}_{session.get('uploaded_file_name')}"
        )
        new_file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], new_file_name)
        with open(new_file_path, "w") as f:
            json.dump(filtered_data, f, indent=4)
        return new_file_path
