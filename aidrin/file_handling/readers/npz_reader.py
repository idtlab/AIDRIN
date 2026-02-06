import numpy as np
import pandas as pd

from aidrin.file_handling.readers.base_reader import BaseFileReader

# Common names for the primary data array in NPZ files
_PRIMARY_ARRAY_NAMES = ['X', 'data', 'arr_0', 'array', 'features', 'values']
# Common names for metadata arrays (not the primary data)
_METADATA_ARRAY_NAMES = ['variable_names', 'feature_names', 'column_names', 'labels',
                         'y', 'target', 'names', 'columns', 'index']


class npzReader(BaseFileReader):
    def read(self):
        npz_data = np.load(self.file_path, allow_pickle=True)
        array_names = list(npz_data.files)

        if not array_names:
            self.logger.warning("NPZ file is empty")
            return pd.DataFrame()

        # Case 1: Single array - use it directly
        if len(array_names) == 1:
            return self._array_to_dataframe(npz_data[array_names[0]], array_names[0])

        # Case 2: Multiple arrays - find the primary data array
        primary_array, primary_name = self._find_primary_array(npz_data, array_names)

        if primary_array is None:
            # Fallback: use the largest array
            primary_name = max(array_names, key=lambda k: npz_data[k].size)
            primary_array = npz_data[primary_name]
            self.logger.info(f"Using largest array '{primary_name}' as primary data")

        # Get column names if available
        column_names = self._get_column_names(npz_data, array_names, primary_array.shape)

        return self._array_to_dataframe(primary_array, primary_name, column_names)

    def _find_primary_array(self, npz_data, array_names):
        """Find the primary data array from multiple arrays."""
        # First, try common primary array names
        for name in _PRIMARY_ARRAY_NAMES:
            if name in array_names:
                self.logger.info(f"Found primary data array: '{name}'")
                return npz_data[name], name

        # Otherwise, find the largest non-metadata array
        candidates = []
        for name in array_names:
            if name.lower() not in [m.lower() for m in _METADATA_ARRAY_NAMES]:
                arr = npz_data[name]
                if arr.size > 1:  # Skip scalar or single-element arrays
                    candidates.append((name, arr, arr.size))

        if candidates:
            # Return the largest candidate
            candidates.sort(key=lambda x: x[2], reverse=True)
            name, arr, _ = candidates[0]
            self.logger.info(f"Selected '{name}' as primary data array (largest non-metadata)")
            return arr, name

        return None, None

    def _get_column_names(self, npz_data, array_names, primary_shape):
        """Extract column/feature names if available."""
        for name in ['variable_names', 'feature_names', 'column_names', 'columns', 'names']:
            if name in array_names:
                names_arr = npz_data[name]
                # Flatten and convert to strings
                if hasattr(names_arr, 'flatten'):
                    names_arr = names_arr.flatten()
                names = [str(n) for n in names_arr]
                self.logger.info(f"Found column names in '{name}': {names[:5]}{'...' if len(names) > 5 else ''}")
                return names
        return None

    def _array_to_dataframe(self, arr, name, column_names=None):
        """Convert a numpy array to a pandas DataFrame.

        Handles arrays of various dimensions:
        - 1D: Single column DataFrame
        - 2D: Rows=samples, Cols=features
        - 3D+: Flatten non-sample dimensions into features
        """
        if arr.ndim == 0:
            # Scalar
            return pd.DataFrame({name: [arr.item()]})

        if arr.ndim == 1:
            # 1D array - single column
            col_name = column_names[0] if column_names else name
            return pd.DataFrame({col_name: arr})

        if arr.ndim == 2:
            # 2D array - rows are samples, columns are features
            df = pd.DataFrame(arr)
            if column_names and len(column_names) == arr.shape[1]:
                df.columns = column_names
            else:
                df.columns = [f"feature_{i}" for i in range(arr.shape[1])]
            return df

        # 3D+ array - flatten spatial/other dimensions into features
        # Assume first dimension is samples (e.g., time steps)
        n_samples = arr.shape[0]
        n_features = np.prod(arr.shape[1:])

        self.logger.info(f"Reshaping {arr.ndim}D array {arr.shape} to 2D: ({n_samples}, {n_features})")

        # Reshape: (samples, d1, d2, ...) -> (samples, d1*d2*...)
        arr_2d = arr.reshape(n_samples, n_features)

        # Generate column names based on original dimensions
        if arr.ndim == 3:
            # For 3D (e.g., time, lat, lon), create informative names
            d1, d2 = arr.shape[1], arr.shape[2]
            col_names = [f"f_{i}_{j}" for i in range(d1) for j in range(d2)]
        else:
            col_names = [f"feature_{i}" for i in range(n_features)]

        df = pd.DataFrame(arr_2d, columns=col_names)

        # Add metadata about original shape
        df.attrs['original_shape'] = arr.shape
        df.attrs['array_name'] = name

        return df

    def parse(self):
        """Return list of array names in the NPZ file."""
        try:
            npz_data = np.load(self.file_path, allow_pickle=True)
            return list(npz_data.files)
        except Exception as e:
            self.logger.error(f"Error parsing NPZ file: {e}")
            return None
