import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader


class parquetReader(BaseFileReader):
    def read(self):
        return pd.read_parquet(self.file_path)

    def read_sample(self, rows, columns):
        from pyarrow.parquet import ParquetFile

        with open(self.file_path, "rb") as handle:
            handle.seek(-8, 2)
            footer = handle.read(8)
            if footer[4:] != b"PAR1" or int.from_bytes(footer[:4], "little") > 256 * 1024:
                return None
            handle.seek(0)
            parquet = ParquetFile(handle)
            if not parquet.num_row_groups or parquet.metadata.row_group(0).total_byte_size > 8 * 1024 * 1024:
                return None
            batches = parquet.iter_batches(batch_size=rows, row_groups=[0], columns=columns, use_threads=False)
            batch = next(batches, None)
            return batch.to_pandas() if batch is not None else None
