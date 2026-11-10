import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader, possible_rounded_integer_columns


class parquetReader(BaseFileReader):
    def read(self):
        frame = pd.read_parquet(self.file_path)
        candidates = [name for name in possible_rounded_integer_columns(frame) if frame[name].hasnans]
        if candidates:
            exact = pd.read_parquet(self.file_path, columns=candidates, dtype_backend="numpy_nullable")
            for name in candidates:
                if pd.api.types.is_integer_dtype(exact[name].dtype):
                    frame[name] = exact[name]
        return frame

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
            if batch is None:
                return None
            # Nullable Arrow integer fields can otherwise become lossy floats.
            return batch.to_pandas(types_mapper=pd.ArrowDtype)
