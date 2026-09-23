import os
import uuid

import h5py
import numpy as np
import pandas as pd
from flask import current_app, session

from aidrin.file_handling.readers.base_reader import BaseFileReader


# Ceiling on the flattened grid table a selection may build, as
# rows * columns * itemsize. Grids are read exactly at full resolution: a
# 10-million-cell grid across a dozen fields is well under a gigabyte in single
# precision and every metric runs over it in seconds, so sampling would trade
# correctness for nothing. The ceiling only stops a selection whose table
# genuinely will not fit.
#
# This counts the finished table, not the peak while building it. Copies made
# on the way put real use at roughly twice the figure, so a ceiling set to the
# memory available will need about half of it.
_DEFAULT_MAX_GRID_BYTES = 2 * 1024**3

# Largest axis still treated as components rather than grid. A component axis
# indexes spatial directions or tensor entries, so it is small; anything longer
# is a dimension of the grid itself.
_MAX_COMPONENT_DIM = 4


def _max_grid_bytes():
    raw = os.environ.get("AIDRIN_HDF5_MAX_GRID_BYTES")
    if not raw:
        return _DEFAULT_MAX_GRID_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_GRID_BYTES
    return value if value > 0 else _DEFAULT_MAX_GRID_BYTES


class hdf5Reader(BaseFileReader):
    def __init__(self, file_path: str, logger, fill_values=None, selected_keys=None):
        super().__init__(file_path, logger)
        # Optional user-supplied fill values merged with auto-detected ones.
        # Accepts any iterable of scalars, e.g. fill_values=[-9999, -1].
        self.fill_values = set(fill_values) if fill_values is not None else set()
        # Explicit keys for Celery workers (no Flask session). None = use session.
        self._explicit_selected_keys = selected_keys

    def _collect_fill_values(self, dataset):
        """Return (explicit, uncertain) sets of numeric missing-data sentinels.

        explicit — safe to replace silently:
            • User-supplied values passed at construction time.
            • ``_FillValue`` attribute (NetCDF/CF convention).
            • ``missing_value`` attribute (older NetCDF convention; may be a
              scalar or a 1-D array of multiple sentinels).
            • The HDF5 native ``dataset.fillvalue`` when it is non-zero *or*
              when fill-value attributes are present (the producer clearly
              cared about missingness, so the native value is intentional).

        uncertain — producer intent is ambiguous, warn before replacing:
            • The HDF5 native ``dataset.fillvalue`` when it equals the dtype
              default (0 / 0.0) *and* no fill-value attributes are present.
              HDF5 always stores a fill value; without an explicit assignment
              it defaults to zero, which is a valid measurement in counts,
              indices, and many physical quantities.

        Only numeric values are collected; non-numeric sentinels are skipped
        because the dtype guard in read() excludes string/compound datasets
        before this method is called.
        """
        explicit = set(self.fill_values)

        for attr_name in ("_FillValue", "missing_value"):
            if attr_name in dataset.attrs:
                raw = dataset.attrs[attr_name]
                for v in np.atleast_1d(raw).ravel():
                    try:
                        explicit.add(float(v))
                    except (TypeError, ValueError):
                        pass

        uncertain = set()
        try:
            native = float(dataset.fillvalue)
            if native not in explicit:
                dtype_default = float(np.zeros(1, dtype=dataset.dtype)[0])
                if native == dtype_default:
                    # Native fill equals the dtype default (0 / 0.0).  HDF5
                    # always stores a fill value; without an explicit producer
                    # assignment it lands here.  Even when fill-value attributes
                    # are present (e.g. _FillValue=-9999), the producer's chosen
                    # sentinel is already in `explicit` — the default zero is
                    # still ambiguous and must not be silently replaced.
                    uncertain.add(native)
                else:
                    # Non-default native fill: the producer explicitly chose
                    # this value, so it is intentional.
                    explicit.add(native)
        except (TypeError, ValueError, RuntimeError):
            # h5py raises RuntimeError when the producer never set a fill value
            # ("fill value is undefined") — treat as no native sentinel.
            pass

        return explicit, uncertain

    def _list_datasets(self):
        """Walk the file and collect metadata for every HDF5 dataset."""
        datasets = []
        with h5py.File(self.file_path, "r") as f:

            def visitor(name, obj):
                if isinstance(obj, h5py.Dataset):
                    datasets.append(
                        {
                            "path": name,
                            "shape": tuple(int(s) for s in obj.shape),
                            "ndim": int(obj.ndim),
                            "dtype": str(obj.dtype),
                            "size": int(obj.size),
                        }
                    )

            f.visititems(visitor)
        return datasets

    def _list_hdf5_groups(self):
        """Return HDF5 group paths (excluding the root group)."""
        groups = []
        with h5py.File(self.file_path, "r") as f:

            def visitor(name, obj):
                if isinstance(obj, h5py.Group):
                    groups.append(name)

            f.visititems(visitor)
        return groups

    def _build_picker_groups(self, datasets):
        """Build selectable groups for the dataset picker UI.

        Groups come from (deepest first) HDF5 group subtrees with 2+ datasets,
        then dot-prefix siblings at the file root (e.g. ``D1.*``).
        """
        paths = {ds["path"] for ds in datasets}
        assigned = set()
        groups = {}

        for group_path in sorted(self._list_hdf5_groups(), key=len, reverse=True):
            prefix = f"{group_path}/"
            members = sorted(p for p in paths if p.startswith(prefix) and p not in assigned)
            if len(members) >= 2:
                groups[group_path] = {
                    "id": group_path,
                    "label": group_path,
                    "type": "hdf5_group",
                    "dataset_paths": members,
                }
                assigned.update(members)

        prefix_map = {}
        for ds in datasets:
            path = ds["path"]
            if path in assigned or "/" in path or "." not in path:
                continue
            prefix = path.split(".", 1)[0]
            prefix_map.setdefault(prefix, []).append(path)

        for prefix, members in prefix_map.items():
            if len(members) >= 2 and prefix not in groups:
                groups[prefix] = {
                    "id": prefix,
                    "label": prefix,
                    "type": "prefix",
                    "dataset_paths": sorted(members),
                }
                assigned.update(members)

        return sorted(groups.values(), key=lambda group: group["label"].lower())

    def _is_pandas_pytables_store(self):
        """True for pandas HDFStore / PyTables frame layouts (e.g. adult.h5)."""
        with h5py.File(self.file_path, "r") as f:
            if "PYTABLES_FORMAT_VERSION" in f.attrs:
                return True

            def visitor(_name, obj):
                if isinstance(obj, h5py.Group):
                    pandas_type = obj.attrs.get("pandas_type")
                    if pandas_type in (b"frame", "frame"):
                        raise StopIteration

            try:
                f.visititems(visitor)
            except StopIteration:
                return True
        return False

    def _is_incompatible_root_layout(self, datasets):
        """True when several root-level 1D arrays have mismatched lengths.

        Files like map_f_case_16p.h5 expose many sibling datasets at ``/`` with
        different shapes. Flattening them into one column is misleading; callers
        should list datasets via parse() and load a specific path instead.
        """
        root = [ds for ds in datasets if "/" not in ds["path"]]
        if len(root) < 2:
            return False
        if not all(ds["ndim"] == 1 for ds in root):
            return False
        lengths = {ds["shape"][0] for ds in root}
        return len(lengths) > 1

    def _is_grouped_hierarchical_layout(self, datasets):
        """True for station-grouped files (EQSIM/rechdf5) with mixed 1D lengths.

        Root may hold only a few scalars while waveforms and metadata live under
        repeated group subtrees (``S_01_01/X``, ``S_01_01/Y``, …).  Pandas
        HDFStore files are excluded so ``adult.h5`` keeps auto-reading.
        """
        if self._is_pandas_pytables_store():
            return False

        nested = [ds for ds in datasets if "/" in ds["path"]]
        if len(nested) < 4:
            return False

        groups = self._build_picker_groups(datasets)
        if len(groups) < 2:
            return False

        lengths = set()
        for ds in nested:
            if ds["ndim"] == 1 and ds["shape"]:
                lengths.add(ds["shape"][0])
        return len(lengths) > 1

    def _has_grid_datasets(self, datasets):
        """True when any dataset is a grid (ndim >= 3).

        Shape-based, unlike the length heuristics above.  A gridded file whose
        1D coordinate arrays happen to share a length -- a square grid, or equal
        step and sample counts -- slips past both heuristics and would otherwise
        be flattened by the legacy path into a ragged object frame.
        """
        return any(ds["ndim"] >= 3 for ds in datasets)

    def _needs_dataset_selection(self, datasets):
        return (
            self._has_grid_datasets(datasets)
            or self._is_incompatible_root_layout(datasets)
            or self._is_grouped_hierarchical_layout(datasets)
        )

    def inventory(self):
        """Summarize datasets and classify the overall layout."""
        datasets = self._list_datasets()
        if not datasets:
            layout = "empty"
        elif len(datasets) == 1:
            layout = "single_dataset"
        elif self._needs_dataset_selection(datasets):
            layout = "multi_dataset"
        else:
            layout = "legacy"
        groups = self._build_picker_groups(datasets) if layout == "multi_dataset" else []
        return {"type": layout, "datasets": datasets, "groups": groups}

    def _normalize_selected_keys(self, keys):
        if isinstance(keys, str):
            keys = [key.strip() for key in keys.split(",") if key.strip()]
        return [str(key) for key in keys if key]

    def _get_selected_dataset_keys(self):
        """Return dataset paths chosen in the Flask session or passed explicitly."""
        if self._explicit_selected_keys is not None:
            return self._normalize_selected_keys(self._explicit_selected_keys)
        try:
            keys = session.get("selected_keys") or []
            return self._normalize_selected_keys(keys)
        except RuntimeError:
            return []

    def _column_name_from_path(self, path, used_names):
        """Prefer the full dataset path so group/station context is preserved.

        Examples: ``S_01_01/X``, ``D1.fill_starts``. Falls back only if the full
        path is already used as a column name (duplicate selection).
        """
        full = path.strip("/") or path
        if full not in used_names:
            return full
        short = path.split("/")[-1] or path
        if short not in used_names:
            return short
        dotted = full.replace("/", ".")
        if dotted not in used_names:
            return dotted
        suffix = 2
        while f"{full}_{suffix}" in used_names:
            suffix += 1
        return f"{full}_{suffix}"

    def _read_compatible_dataset_paths(self, paths):
        """Merge multiple same-length 1D datasets into one DataFrame."""
        if not paths:
            return None

        columns = {}
        expected_len = None

        for path in paths:
            with h5py.File(self.file_path, "r") as f:
                if path not in f:
                    self.logger.warning("HDF5 dataset path not found: %s", path)
                    return None
                obj = f[path]
                if not isinstance(obj, h5py.Dataset):
                    self.logger.warning("HDF5 path is not a dataset: %s", path)
                    return None

                data = obj[()]
                data = self._apply_fill_values(data, obj, path)

                if getattr(data, "ndim", 0) != 1:
                    self.logger.warning(
                        "HDF5 multi-select requires 1D datasets; '%s' has ndim=%s",
                        path,
                        getattr(data, "ndim", None),
                    )
                    return None

                length = int(data.shape[0])
                if expected_len is None:
                    expected_len = length
                elif length != expected_len:
                    self.logger.warning(
                        "HDF5 selected datasets have incompatible lengths "
                        "(%d vs %d); cannot merge into one table.",
                        expected_len,
                        length,
                    )
                    return None

                col_name = self._column_name_from_path(path, set(columns))
                columns[col_name] = data

        df = pd.DataFrame(columns)
        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def _grid_column_names(self, path, trailing, used):
        """One column per component: a scalar field gives one, a vector D."""
        base = self._column_name_from_path(path, used)
        if not trailing:
            return [(base, ())]
        return [
            (f"{base}_" + "_".join(str(i) for i in idx), idx)
            for idx in np.ndindex(*trailing)
        ]

    @staticmethod
    def _is_image(dataset):
        """True when a dataset declares itself an image.

        The Image and Palette specification marks these with ``CLASS="IMAGE"``.
        Their axes are height, width and colour components, which flatten into
        a table perfectly well and mean nothing once there: a photograph scores
        a duplicity of 0.4 because many pixels share a colour, and an outlier
        fraction over its channels. AIDRIN assesses tabular data, so say that
        rather than return numbers nobody should act on.
        """
        value = dataset.attrs.get("CLASS")
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        return value == "IMAGE"

    def _selection_is_gridded(self, inv, selected):
        """True when a selection should be flattened to one row per grid cell.

        Rank 3 and above is a grid on its own: there is no other reading of it.
        Rank 2 is ambiguous, because a single 2D dataset is an ordinary table of
        rows and columns and is read as one. Several 2D datasets of the same
        shape are not a table each; they are fields sampled on a shared grid,
        and the only way to put them in one frame is a column each. That is how
        netCDF and PDE benchmarks store a static field next to its coordinates.
        """
        shapes = {ds["path"]: ds["shape"] for ds in inv["datasets"]}
        picked = [shapes.get(p.strip("/")) for p in selected]
        picked = [shape for shape in picked if shape is not None]
        if not picked:
            return False
        if any(len(shape) >= 3 for shape in picked):
            return True
        return len(picked) > 1 and len(set(picked)) == 1 and len(picked[0]) == 2

    def _dominant_grid_shape(self):
        """The shape most datasets in the file sit on, or None.

        A field's own shape cannot say whether its last axis is a component or
        another spatial one -- ``(T, Y, X, 3)`` could be either. Its neighbours
        can: when most datasets in the file stop at ``(T, Y, X)``, the extra axis
        is components. This reads the file's own structure rather than any one
        format's metadata, so it resolves a vector field selected on its own
        without knowing which project produced it.
        """
        shapes = [ds["shape"] for ds in self._list_datasets() if ds["ndim"] >= 2]
        if not shapes:
            return None

        # Score each candidate by how many datasets it is a *prefix* of, not how
        # many match it exactly: a grid is the start of every field that sits on
        # it, and counting exact matches lets the widest fields outvote it, two
        # tensors at (*grid, D, D) electing themselves over one scalar at
        # (*grid).
        #
        # A short prefix would then win every time -- a 2D per-sample time array
        # at (S, T) precedes every field at (S, T, Y, X) -- so a candidate only
        # counts when what follows it could be components. Components index
        # spatial directions or tensor entries and so are small; an axis of 512
        # is grid. This is what separates the grid from anything that merely
        # comes before it.
        best = None
        for candidate in set(shapes):
            covered = [sh for sh in shapes if sh[: len(candidate)] == candidate]
            if len(covered) < 2:
                # One dataset on a shape is not a consensus, so it says nothing
                # about which axes are grid.
                continue
            if any(
                dim > _MAX_COMPONENT_DIM
                for sh in covered
                for dim in sh[len(candidate):]
            ):
                continue
            # Widest agreement first, then the shortest shape, since a shorter
            # prefix of the same datasets is the grid and the longer one carries
            # components. Ties end on the shape itself so the answer does not
            # depend on the order h5py happens to walk the file in.
            key = (len(covered), -len(candidate), candidate)
            if best is None or key > best[0]:
                best = (key, candidate)
        return best[1] if best else None

    def _resolve_grid_base(self, specs, file_grid):
        """Resolve the grid every selected dataset sits on.

        ``specs`` is a list of ``(path, shape, dtype)``. Returns
        ``(base_shape, error)`` where ``error`` is a user-facing message when the
        selection cannot share rows, and ``None`` when it can.

        The grid the rest of the file agrees on wins when every selected dataset
        starts with it, which is what resolves a vector field selected on its
        own. Otherwise the shortest selected shape stands in, which is right
        whenever the selection itself contains a scalar field.
        """
        if file_grid is not None and all(
            shape[: len(file_grid)] == file_grid for _p, shape, _d in specs
        ):
            base = file_grid
        else:
            base = min((spec[1] for spec in specs), key=len)
            # Any lone high-rank dataset is ambiguous in principle, but warning
            # on all of them trains the reader to ignore the warning. Two
            # conditions make "grid plus components" the plausible reading: a
            # trailing axis of 2 or 3, since a component axis holds one entry
            # per spatial dimension while a grid axis is normally far longer,
            # and at least two axes ahead of it, since a rank-2 array with a
            # short second axis is far more often an ordinary table.
            if len(specs) == 1 and len(base) >= 3 and base[-1] in (2, 3):
                self.logger.warning(
                    "HDF5 dataset '%s' has shape %s and is selected alone, and no "
                    "other dataset in the file shares a grid that would identify a "
                    "trailing component axis, so every axis is read as grid. If it "
                    "is a vector field, select it together with a scalar field on "
                    "the same grid so its components become separate columns.",
                    specs[0][0],
                    base,
                )

        for path, shape, _dtype in specs:
            if shape[: len(base)] != base:
                return None, (
                    f"'{path}' has shape {shape}, which does not start with the "
                    f"grid {base} shared by the rest of the selection. Select "
                    "datasets that share one grid."
                )
        return base, None

    def validate_selection(self, keys):
        """Check a selection before it is stored, returning a message or None.

        The dataset picker and the reader have to agree on what a usable
        selection is, so the rule lives here and both call in rather than the
        picker keeping a second copy that can fall behind.
        """
        keys = self._normalize_selected_keys(keys)
        if not keys:
            return "No datasets selected."

        with h5py.File(self.file_path, "r") as f:
            specs = []
            for key in keys:
                if key not in f:
                    return f"Unknown dataset: {key}"
                obj = f[key]
                if not isinstance(obj, h5py.Dataset):
                    return f"'{key}' is not a dataset."
                if self._is_image(obj):
                    return (
                        f"'{key}' is an image. AIDRIN does not support images in "
                        "HDF5 files."
                    )
                if obj.dtype.subdtype is not None:
                    return (
                        f"'{key}' has an array dtype ({obj.dtype}), which AIDRIN "
                        "does not read as a grid."
                    )
                specs.append((key, tuple(int(x) for x in obj.shape), obj.dtype))

            if any(len(shape) >= 3 for _p, shape, _d in specs):
                _base, error = self._resolve_grid_base(specs, self._dominant_grid_shape())
                return error

        if len(specs) > 1:
            for path, shape, _dtype in specs:
                if len(shape) != 1:
                    return (
                        f"'{path}' is not a 1D array. Select 1D datasets with the "
                        "same length, datasets that share a grid, or a single 2D "
                        "dataset."
                    )
            lengths = {shape[0] if shape else 0 for _p, shape, _d in specs}
            if len(lengths) > 1:
                return "Selected datasets must have the same length to merge into one table."
        return None

    def _read_grid_dataset_paths(self, paths):
        """Flatten aligned grid datasets into one row per cell, one column per field.

        Every selected dataset must share a common leading shape -- the grid.
        Vector and tensor fields are commonly stored as ``(*grid, D)`` and
        ``(*grid, D, D)``, so a dataset carrying extra trailing dimensions
        contributes one column per component (``field_0``, ``field_1``) rather
        than being refused for not matching the scalar fields.

        Shapes are read from metadata first so an oversized selection is rejected
        before anything is loaded.
        """
        if not paths:
            return None

        with h5py.File(self.file_path, "r") as f:
            specs = []
            for path in paths:
                if path not in f:
                    self.logger.warning("HDF5 dataset path not found: %s", path)
                    return None
                obj = f[path]
                if not isinstance(obj, h5py.Dataset):
                    self.logger.warning("HDF5 path is not a dataset: %s", path)
                    return None
                if self._is_image(obj):
                    self.logger.warning(
                        "HDF5 dataset '%s' is an image. AIDRIN does not support "
                        "images in HDF5 files.",
                        path,
                    )
                    return None
                if obj.dtype.subdtype is not None:
                    # HDF5 can carry a dimension in the dtype rather than the
                    # shape, and then shape no longer says how many values a
                    # cell holds. Rare enough not to model.
                    self.logger.warning(
                        "HDF5 dataset '%s' has an array dtype (%s), which AIDRIN "
                        "does not read as a grid.",
                        path,
                        obj.dtype,
                    )
                    return None
                specs.append((path, tuple(int(x) for x in obj.shape), obj.dtype))

            base, error = self._resolve_grid_base(specs, self._dominant_grid_shape())
            if error:
                self.logger.warning("%s", error)
                return None

            rows = 1
            for dim in base:
                rows *= dim
            projected = 0
            for path, shape, dtype in specs:
                components = 1
                for dim in shape[len(base):]:
                    components *= dim
                # _apply_fill_values casts to float64 when it replaces a
                # sentinel, so a column with fill-value attributes can land at
                # double the source itemsize. Project the larger of the two
                # rather than admit a selection that then does not fit.
                itemsize = int(dtype.itemsize)
                explicit, _uncertain = self._collect_fill_values(f[path])
                if explicit:
                    itemsize = max(itemsize, 8)
                projected += rows * components * itemsize

            budget = _max_grid_bytes()
            if projected > budget:
                self.logger.warning(
                    "HDF5 grid selection would build a %.2f GB table (%d rows from "
                    "grid %s), over the %.2f GB ceiling. Select fewer datasets, or "
                    "raise AIDRIN_HDF5_MAX_GRID_BYTES if the memory is available.",
                    projected / 1024**3,
                    rows,
                    base,
                    budget / 1024**3,
                )
                return None

            columns = {}
            for path, shape, _dtype in specs:
                data = self._apply_fill_values(f[path][()], f[path], path)
                trailing = shape[len(base):]
                for name, idx in self._grid_column_names(path, trailing, set(columns)):
                    values = data[(Ellipsis,) + idx] if idx else data
                    columns[name] = np.asarray(values).reshape(-1)

        df = pd.DataFrame(columns)
        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def _apply_fill_values(self, data, dataset, name):
        """Replace fill-value sentinels with NaN for numeric dataset arrays."""
        if not (hasattr(data, "dtype") and data.dtype.kind in ("f", "i", "u")):
            return data

        explicit_fills, _uncertain_fills = self._collect_fill_values(dataset)
        if not explicit_fills:
            return data

        matched = {fv for fv in explicit_fills if np.any(data == fv)}
        if not matched:
            return data

        mask = np.zeros(data.shape, dtype=bool)
        for fv in matched:
            mask |= data == fv
        n_replaced = int(mask.sum())

        self.logger.info(
            f"Dataset '{name}': replaced "
            f"{n_replaced}/{data.size} value(s) "
            f"matching explicit fill sentinel(s) "
            f"{matched} with NaN."
        )

        data = data.astype(np.float64)
        data[mask] = np.nan
        return data

    def _decode_bytes(self, df):
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(
                    lambda x: x.decode("utf-8") if isinstance(x, bytes) else x
                )
        return df

    def _read_dataset_path(self, path):
        """Load one HDF5 dataset path into a DataFrame."""
        with h5py.File(self.file_path, "r") as f:
            if path not in f:
                self.logger.warning("HDF5 dataset path not found: %s", path)
                return None
            obj = f[path]
            if not isinstance(obj, h5py.Dataset):
                self.logger.warning("HDF5 path is not a dataset: %s", path)
                return None

            if self._is_image(obj):
                # A 2D image reaches this path rather than the grid one, and
                # would otherwise be read as an ordinary table of pixel rows.
                self.logger.warning(
                    "HDF5 dataset '%s' is an image. AIDRIN does not support "
                    "images in HDF5 files.",
                    path,
                )
                return None

            # Read ndim off the h5py metadata, not the loaded array: grids are
            # exactly what this refuses and also the largest datasets, so
            # materializing one only to reject it would exhaust memory.
            if int(getattr(obj, "ndim", 0)) >= 3:
                self.logger.warning(
                    "HDF5 dataset '%s' has ndim=%s; refusing to aggregate or flatten. "
                    "Select a 1D (or single 2D) dataset via selected_keys.",
                    path,
                    obj.ndim,
                )
                return None

            data = obj[()]
            data = self._apply_fill_values(data, obj, path)

            col_name = self._column_name_from_path(path, set())
            if getattr(data, "ndim", 0) == 0:
                df = pd.DataFrame({col_name: [data]})
            elif data.ndim == 1:
                df = pd.DataFrame({col_name: data})
            else:
                try:
                    df = pd.DataFrame(data)
                except Exception:
                    df = pd.DataFrame(data.tolist())
                df.columns = [str(col) for col in df.columns]

        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def _select_store_key(self, keys):
        """Resolve which HDFStore frame to load.

        Honours an explicit or session selection in either key form (pandas
        reports ``/first`` while callers usually pass ``first``).  When nothing
        is selected and the store holds more than one frame, warn before
        defaulting so a multi-frame file never silently reports just one table.
        """
        available = {key.strip("/"): key for key in keys}
        requested = self._get_selected_dataset_keys()
        for want in requested:
            match = available.get(want.strip("/"))
            if match:
                return match

        if requested:
            self.logger.warning(
                "None of the selected keys %s name a frame in '%s' (available: %s).",
                requested,
                self.file_path,
                sorted(available),
            )
        if len(keys) > 1:
            self.logger.warning(
                "Pandas HDFStore '%s' holds %d frames (%s); reading '%s'. "
                "Select a key to analyze a different one.",
                self.file_path,
                len(keys),
                sorted(available),
                keys[0].strip("/"),
            )
        return keys[0]

    def _read_pandas_store(self):
        """Let pandas decode an HDFStore file instead of walking its blocks.

        Both store formats hold the frame behind pandas' private block layout
        (``axis0``/``block0_values`` for ``fixed``, ``table`` plus an
        ``_i_table`` index for ``table``).  Walking those datasets as if they
        were independent arrays folds the row index and the column-name arrays
        into the data, so only pandas can map them back to the original frame.
        """
        try:
            with pd.HDFStore(self.file_path, mode="r") as store:
                keys = list(store.keys())
                if not keys:
                    self.logger.warning(
                        "Pandas HDFStore contains no frames: %s", self.file_path
                    )
                    return None
                df = store.get(self._select_store_key(keys))
        except Exception as exc:
            self.logger.warning(
                "Could not decode pandas HDFStore '%s' (%s); "
                "falling back to raw dataset traversal.",
                self.file_path,
                exc,
            )
            return None

        if isinstance(df, pd.Series):
            df = df.to_frame()
        if not isinstance(df, pd.DataFrame):
            self.logger.warning(
                "Pandas HDFStore frame has unsupported type %s", type(df).__name__
            )
            return None

        df = self._decode_bytes(df)
        df.columns = [str(col) for col in df.columns]
        if df.empty:
            return None
        return df

    def read(self):
        try:
            inv = self.inventory()

            # An explicit selection is explicit intent, so it is honoured before
            # any layout branch. Reaching those first meant a selection was
            # silently dropped unless the file happened to be typed
            # "multi_dataset": a lone grid is typed "single_dataset", and a file
            # mixing 2D fields with 1D coordinates is typed "legacy", and both
            # went to the walk below, which ignores the selection and stacks
            # every dataset into one ragged frame.
            #
            # A pandas HDFStore is the exception: its keys name frames rather
            # than dataset paths, so _read_pandas_store resolves them.
            selected = self._get_selected_dataset_keys()
            if selected and inv["datasets"] and not self._is_pandas_pytables_store():
                if self._selection_is_gridded(inv, selected):
                    return self._read_grid_dataset_paths(selected)
                known = {ds["path"] for ds in inv["datasets"]}
                if all(key.strip("/") in known for key in selected):
                    if len(selected) == 1:
                        return self._read_dataset_path(selected[0])
                    return self._read_compatible_dataset_paths(selected)

            if inv["type"] == "multi_dataset":
                n = len(inv["datasets"])
                self.logger.warning(
                    "HDF5 file has %d datasets in an incompatible layout; "
                    "refusing to flatten into one table. "
                    "Use parse() / inventory() to list paths and select compatible ones.",
                    n,
                )
                return None
            if inv["type"] == "empty":
                self.logger.warning("No datasets found in HDF5 file")
                return None

            if self._is_pandas_pytables_store():
                store_df = self._read_pandas_store()
                if store_df is not None:
                    return store_df

            # Grids never reach the flattening below: it walks every dataset and
            # builds one row per element, turning an N-D array into cells that
            # hold Python lists.  Single-dataset grids land here too, since
            # inventory() short-circuits them to "single_dataset".
            if self._has_grid_datasets(inv["datasets"]):
                grids = [
                    f"{ds['path']}{ds['shape']}" for ds in inv["datasets"] if ds["ndim"] >= 3
                ]
                self.logger.warning(
                    "HDF5 file holds %d grid dataset(s) with ndim >= 3 (%s); refusing to "
                    "aggregate or flatten. Use parse() / inventory() to list paths and "
                    "select a 1D (or single 2D) dataset via selected_keys.",
                    len(grids),
                    ", ".join(grids[:5]),
                )
                return None

            rows = []
            # Clean up byte strings in all object columns

            def decode_bytes(df):
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].apply(
                            lambda x: x.decode("utf-8") if isinstance(x, bytes) else x
                        )
                return df

            def convert_numpy_types(obj):
                """Recursively convert numpy types to Python native types"""
                try:
                    if hasattr(obj, 'item'):  # numpy scalar
                        return obj.item()
                    elif isinstance(obj, (list, tuple)):
                        return [convert_numpy_types(item) for item in obj]
                    elif isinstance(obj, dict):
                        return {str(k): convert_numpy_types(v) for k, v in obj.items()}
                    elif hasattr(obj, 'dtype'):  # numpy array
                        if obj.size == 1:  # Single element array
                            return obj.item()
                        else:  # Multi-element array
                            return obj.tolist()
                    else:
                        return obj
                except Exception as e:
                    self.logger.warning(f"Error converting numpy type: {e}")
                    return str(obj)  # Fallback to string representation

            def recurse(name, obj, path=[]):
                try:
                    if isinstance(obj, h5py.Dataset):
                        data = obj[()]
                        data = self._apply_fill_values(data, obj, name)
                        # If it's a 1D or structured dataset, load it into dicts
                        if isinstance(data, (list, tuple)) or hasattr(data, "dtype"):
                            try:
                                df = pd.DataFrame(data)
                            except Exception:
                                df = pd.DataFrame(data.tolist())  # base
                            for _, row in df.iterrows():
                                try:
                                    row_dict = row.to_dict()
                                    # Convert any numpy types to Python native types
                                    row_dict = convert_numpy_types(row_dict)
                                    rows.append(row_dict)
                                except Exception as e:
                                    self.logger.warning(f"Error processing row: {e}")
                                    # Try to process the row with basic conversion
                                    try:
                                        basic_row = {}
                                        for col in row.index:
                                            try:
                                                value = row[col]
                                                if hasattr(value, 'item'):
                                                    basic_row[str(col)] = value.item()
                                                else:
                                                    basic_row[str(col)] = str(value)
                                            except Exception:
                                                basic_row[str(col)] = str(value)
                                        rows.append(basic_row)
                                    except Exception as e2:
                                        self.logger.warning(f"Failed to process row even with basic conversion: {e2}")
                                        continue
                        else:
                            # Scalar or flat dataset - ensure data is hashable
                            try:
                                # Convert any numpy types to Python native types
                                data = convert_numpy_types(data)
                                row_dict = {"value": data}
                                rows.append(row_dict)
                            except Exception as e:
                                self.logger.warning(f"Error processing scalar data: {e}")
                                # Try basic conversion
                                try:
                                    if hasattr(data, 'item'):
                                        row_dict = {"value": data.item()}
                                    else:
                                        row_dict = {"value": str(data)}
                                    rows.append(row_dict)
                                except Exception as e2:
                                    self.logger.warning(f"Failed to process scalar data even with basic conversion: {e2}")
                                    # Skip this data point
                                    pass
                except Exception as e:
                    self.logger.warning(f"Error in recurse function: {e}")
                    return

            with h5py.File(self.file_path, "r") as f:

                def visit(name, obj):
                    recurse(name, obj, name.strip("/").split("/"))

                f.visititems(visit)
            df = pd.DataFrame(rows)
            df = decode_bytes(df)

            # Ensure all column names are strings to avoid numpy array issues
            if hasattr(df, 'columns') and len(df.columns) > 0:
                df.columns = [str(col) for col in df.columns]

            # Check if DataFrame is empty and log warning
            if df.empty:
                self.logger.warning("No data was successfully processed from HDF5 file")
                return None

            return df
        except Exception as e:
            self.logger.error(f"Error while reading: {e}")
            return None

    def parse(self):
        datasets = self._list_datasets()
        paths = [ds["path"] for ds in datasets]
        self.logger.info("dataset paths found: %s", paths)
        return paths

    def filter(self, kept_keys):
        if isinstance(kept_keys, str):
            kept_keys = kept_keys.split(",")
        # Ensure all keys are strings and hashable to avoid "unhashable type" errors
        filtered_keys = set()
        for g in kept_keys:
            try:
                # Convert to string and ensure it's hashable
                key_str = str(g).strip("/")
                # Test if it's hashable by trying to add to set
                filtered_keys.add(key_str)
            except (TypeError, ValueError) as e:
                # If conversion fails, skip this key and log the error
                self.logger.warning(f"Skipping unhashable key {g}: {e}")
                continue

        new_file_name = (
            f"filtered_{uuid.uuid4().hex}_{session.get('uploaded_file_name')}"
        )
        new_file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], new_file_name)
        with (
            h5py.File(self.file_path, "r") as src,
            h5py.File(new_file_path, "w") as tgt,
        ):

            def copy_group(path, src_group, tgt_group):
                for name, obj in src_group.items():
                    full_path = f"{path}/{name}".strip("/")
                    if isinstance(obj, h5py.Group):
                        if full_path in filtered_keys:
                            tgt_subgroup = tgt_group.create_group(name)
                            copy_group(full_path, obj, tgt_subgroup)
                        else:
                            copy_group(full_path, obj, tgt_group)
                    elif isinstance(obj, h5py.Dataset):
                        if path.strip("/") in filtered_keys:
                            tgt_group.create_dataset(name, data=obj[()])

            copy_group("", src, tgt)

        return new_file_path
