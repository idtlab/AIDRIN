"""
Lightweight data profiler for structured datasets.

Given a YAML config, the profiler:
1. Loads the dataset (CSV path or custom data loader).
2. Computes summary statistics split into numeric and categorical views.
3. Returns a JSON-friendly dictionary and can optionally write it to disk.

Dependencies: pandas, pyyaml (both installed with ``pip install "aidrin[agentic]"``).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml


class DataProfiler:
    """Encapsulated profiler to integrate into larger frameworks."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        compact: bool | None = None,
        max_columns: int = 3,
        max_metadata_rows: int = 20,
        max_metadata_bytes: int = 4000,
    ) -> None:
        default_config = Path(__file__).resolve().parent.parent.parent / "configs" / "healthcare.yaml"
        chosen = Path(config_path) if config_path else default_config
        self.config_path = self._resolve_existing(chosen, fallback_base=default_config.parent)
        paths, profiling_full = self._load_config(self.config_path)
        self.data_path: Path | None = paths.get("data_csv")
        self.data_loader_path: str | None = paths.get("data_loader")
        self.metadata_path: Path = paths["metadata_csv"]
        self.ontology_cfg = paths.get("ontology_mapping", {})
        self.compact = compact if compact is not None else not profiling_full
        self.max_columns = max_columns
        self.max_metadata_rows = max_metadata_rows
        self.max_metadata_bytes = max_metadata_bytes

    @staticmethod
    def _resolve_existing(path: Path, fallback_base: Path | None = None) -> Path:
        if path.exists():
            return path
        if not path.is_absolute() and fallback_base:
            candidate = fallback_base / path
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"Path not found: {path}")

    @staticmethod
    def _resolve_child(base: Path, child: Path) -> Path:
        if child.is_absolute():
            return child
        candidate = (base / child).resolve()
        if candidate.exists():
            return candidate
        alt = (base.parent / child).resolve()
        if alt.exists():
            return alt
        return candidate

    def _load_config(self, config_path: Path) -> tuple[dict[str, Any], bool]:
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}

        try:
            data_csv_raw = Path(cfg["paths"]["data_csv"]) if cfg.get("paths", {}).get("data_csv") else None
            metadata_csv_raw = Path(cfg["paths"]["metadata_csv"])
            data_loader = cfg.get("paths", {}).get("data_loader")
        except Exception as exc:
            raise ValueError("Config must define paths.metadata_csv and either paths.data_csv or paths.data_loader") from exc

        profiling_cfg = cfg.get("profiling", {}) or {}
        profiling_full = bool(profiling_cfg.get("full_summary", False))
        ontology_cfg = profiling_cfg.get("ontology_mapping", {}) or profiling_cfg.get("ontology_mapper", {}) or {}

        base = config_path.parent
        data_csv = self._resolve_child(base, data_csv_raw) if data_csv_raw else None
        metadata_csv = self._resolve_child(base, metadata_csv_raw)
        if data_csv is not None:
            data_csv = self._resolve_existing(data_csv, fallback_base=None)
        metadata_csv = self._resolve_existing(metadata_csv, fallback_base=None)

        ontology_cfg_resolved = self._resolve_ontology_cfg(base, ontology_cfg)

        return {
            "data_csv": data_csv,
            "data_loader": data_loader,
            "metadata_csv": metadata_csv,
            "ontology_mapping": ontology_cfg_resolved,
        }, profiling_full

    def _resolve_ontology_cfg(self, base: Path, cfg: dict[str, Any]) -> dict[str, Any]:
        if not cfg:
            return {"enabled": False}

        resolved: dict[str, Any] = {"enabled": bool(cfg.get("enabled", False))}
        mapping_file = cfg.get("mapping_file")
        if mapping_file:
            path_candidate = Path(mapping_file)
            if path_candidate.suffix:
                resolved_path = self._resolve_child(base, path_candidate)
                if resolved_path.exists():
                    resolved["mapping_file"] = str(resolved_path)
                else:
                    fallback = base / "ontology_mapper.py"
                    if fallback.exists():
                        resolved["mapping_file"] = str(fallback)
                    else:
                        fallback = base.parent / "ontology_mapper.py"
                        if fallback.exists():
                            resolved["mapping_file"] = str(fallback)
            else:
                resolved["mapping_module"] = mapping_file
        else:
            fallback_path = base / "ontology_mapper.py"
            if fallback_path.exists():
                resolved["mapping_file"] = str(fallback_path)
            else:
                fallback_path = base.parent / "ontology_mapper.py"
                if fallback_path.exists():
                    resolved["mapping_file"] = str(fallback_path)
        mapper_name = cfg.get("mapper_name")
        if mapper_name:
            resolved["mapper_name"] = mapper_name
        return resolved

    @staticmethod
    def summarize_numeric(df: pd.DataFrame) -> dict[str, dict[str, float]]:
        numeric = df.select_dtypes(include="number")
        if numeric.empty:
            return {}

        stats: dict[str, dict[str, float]] = {}
        total = len(df)
        desc = numeric.describe().transpose()[["count", "mean", "std", "min", "max"]]
        for col, row in desc.iterrows():
            missing_ratio = float((total - row["count"]) / total) if total else 0.0
            stats[col] = {
                "count": int(row["count"]),
                "mean": float(round(row["mean"], 4)) if pd.notna(row["mean"]) else None,
                "std": float(round(row["std"], 4)) if pd.notna(row["std"]) else None,
                "min": float(round(row["min"], 4)) if pd.notna(row["min"]) else None,
                "max": float(round(row["max"], 4)) if pd.notna(row["max"]) else None,
                "missing_ratio": float(round(missing_ratio, 4)),
            }
        return stats

    @staticmethod
    def summarize_categorical(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
        cats = df.select_dtypes(exclude="number")
        if cats.empty:
            return {}

        stats: dict[str, dict[str, Any]] = {}
        for col in cats.columns:
            series = cats[col]
            value_counts = series.value_counts(dropna=True)
            top_value = value_counts.index[0] if not value_counts.empty else None
            stats[col] = {
                "count": int(series.count()),
                "n_unique": int(series.nunique(dropna=True)),
                "top": top_value,
                "missing_count": int(series.isna().sum()),
                "missing_ratio": float(round(series.isna().mean(), 4)),
            }
        return stats

    def read_metadata(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Metadata file not found: {path}")

        suffix = path.suffix.lower()
        is_text = suffix in {".txt", ".md", ".rst", ".log"} or suffix == ""

        if is_text:
            content = path.read_text(encoding="utf-8", errors="ignore")
            raw_bytes = content.encode("utf-8")
            truncated = len(raw_bytes) > self.max_metadata_bytes
            snippet = raw_bytes[: self.max_metadata_bytes].decode("utf-8", errors="ignore") if truncated else content
            return {
                "type": "text",
                "truncated": truncated,
                "bytes": len(raw_bytes),
                "content": snippet,
            }

        meta_df = pd.read_csv(path)
        total_rows = len(meta_df)
        truncated = total_rows > self.max_metadata_rows
        if truncated:
            meta_df = meta_df.head(self.max_metadata_rows)

        if "column" in meta_df.columns:
            rows = meta_df.set_index("column").to_dict(orient="index")
        else:
            rows = meta_df.to_dict(orient="records")

        return {
            "type": "table",
            "truncated": truncated,
            "total_rows": total_rows,
            "rows": rows,
        }

    def _load_mapper_function(self) -> tuple[Callable[[list[str]], dict[str, Any]] | None, str | None]:
        cfg = self.ontology_cfg
        if not cfg.get("enabled"):
            return None, None
        func_name = cfg.get("mapper_name")
        if not func_name:
            return None, "mapper_name not provided"

        module_path = cfg.get("mapping_file")
        fallback_path = getattr(self, "data_path", None)
        fallback_path = fallback_path.parent.parent / "ontology_mapper.py" if fallback_path else None
        for candidate in (module_path, fallback_path):
            if not candidate:
                continue
            path_obj = Path(candidate)
            if path_obj.exists() and path_obj.suffix == ".py":
                spec = importlib.util.spec_from_file_location("ontology_mapper_dynamic", str(path_obj))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    try:
                        spec.loader.exec_module(module)  # type: ignore[arg-type]
                    except Exception as exc:
                        return None, str(exc)
                    func = getattr(module, func_name, None)
                    if callable(func):
                        return func, None

        module_name = cfg.get("mapping_module")
        if module_name:
            try:
                module = importlib.import_module(module_name)
                func = getattr(module, func_name, None)
                if callable(func):
                    return func, None
            except Exception as exc:
                return None, str(exc)
        return None, "ontology mapper function not found"

    def _run_ontology_mapping(self, df: pd.DataFrame) -> dict[str, Any]:
        mapper, load_error = self._load_mapper_function()
        if mapper is None:
            return {
                "enabled": bool(self.ontology_cfg.get("enabled", False)),
                "mapper": self.ontology_cfg.get("mapper_name"),
                "source": self.ontology_cfg.get("mapping_file") or self.ontology_cfg.get("mapping_module"),
                "error": load_error or "Ontology mapper not available; check mapping_file/mapping_module and mapper_name.",
            }

        try:
            result = mapper()
            return {
                "enabled": True,
                "mapper": self.ontology_cfg.get("mapper_name"),
                "source": self.ontology_cfg.get("mapping_file") or self.ontology_cfg.get("mapping_module"),
                "mapping": result,
            }
        except Exception as exc:
            return {
                "enabled": True,
                "mapper": self.ontology_cfg.get("mapper_name"),
                "source": self.ontology_cfg.get("mapping_file") or self.ontology_cfg.get("mapping_module"),
                "error": str(exc),
            }

    def profile(self) -> dict[str, Any]:
        """Produce combined summary stats and metadata."""
        if self.data_path is None and not self.data_loader_path:
            raise FileNotFoundError("No data source provided. Set paths.data_loader or paths.data_csv in config.")

        if self.data_loader_path:
            df = self._load_via_loader(self.data_loader_path)
        else:
            if not self.data_path.exists():
                raise FileNotFoundError(f"Data file not found: {self.data_path}")
            df = pd.read_csv(self.data_path, low_memory=False)

        num_cols = list(df.select_dtypes(include="number").columns)
        cat_cols = list(df.select_dtypes(exclude="number").columns)

        summary = {
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "missing_overall_ratio": float(round(df.isna().stack().mean(), 4)),
            "numeric_columns": num_cols,
            "categorical_columns": cat_cols,
            "numeric": self.summarize_numeric(df),
            "categorical": self.summarize_categorical(df),
        }

        metadata = self.read_metadata(self.metadata_path)
        ontology = self._run_ontology_mapping(df)

        if self.compact:
            summary["numeric"] = self._trim_dict(summary["numeric"], self.max_columns)
            summary["categorical"] = self._trim_dict(summary["categorical"], self.max_columns)
            summary["notes"] = (
                f"Compact mode: stats limited to {self.max_columns} columns per type; "
                "set profiling.full_summary: true in YAML or pass --full to disable trimming."
            )
        else:
            summary["notes"] = "Full summary mode."

        return {
            "data_path": str(self.data_path) if self.data_path else f"loader:{self.data_loader_path}",
            "metadata_path": str(self.metadata_path),
            "summary": summary,
            "metadata": metadata,
            "ontology_mapping": ontology,
        }

    def save(self, payload: dict[str, Any], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    @staticmethod
    def _trim_dict(data: dict[str, Any], limit: int) -> dict[str, Any]:
        return dict(list(data.items())[:limit])

    def _load_via_loader(self, path: str) -> pd.DataFrame:
        if ":" not in path:
            raise ValueError("paths.data_loader must be in form 'module_or_file.py:function'")
        module_name, func_name = path.split(":", 1)
        p = Path(module_name)
        if p.suffix == ".py":
            # Resolve relative to the config file's directory
            candidates = [p, self.config_path.parent / p]
            for candidate in candidates:
                candidate = candidate.resolve()
                if candidate.exists():
                    spec = importlib.util.spec_from_file_location(candidate.stem, str(candidate))
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)  # type: ignore[arg-type]
                        func = getattr(mod, func_name, None)
                        if not callable(func):
                            raise ValueError(f"Loader function '{func_name}' not found in {candidate}")
                        df = func()
                        if not isinstance(df, pd.DataFrame):
                            raise TypeError("Data loader must return a pandas DataFrame")
                        return df
            raise FileNotFoundError(f"Loader file not found: {module_name} (looked relative to config and cwd)")
        module = importlib.import_module(module_name)
        func = getattr(module, func_name, None)
        if not callable(func):
            raise ValueError(f"Loader function '{func_name}' not found in {module_name}")
        df = func()
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Data loader must return a pandas DataFrame")
        return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate dataset summary and metadata view.")
    parser.add_argument("-c", "--config", type=Path, required=True,
                        help="Path to YAML config containing data paths and profiling settings.")
    parser.add_argument("-o", "--output", type=Path,
                        help="Optional path to write JSON results.")
    parser.add_argument("--full", action="store_true",
                        help="Disable compact trimming (may produce large output).")
    parser.add_argument("--max-columns", type=int, default=3,
                        help="Max columns per type to include when compact mode is on.")
    parser.add_argument("--max-metadata-rows", type=int, default=20,
                        help="Max rows to return for tabular metadata.")
    parser.add_argument("--max-metadata-bytes", type=int, default=4000,
                        help="Max bytes to return for text metadata.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profiler = DataProfiler(
        config_path=args.config,
        compact=False if args.full else None,
        max_columns=args.max_columns,
        max_metadata_rows=args.max_metadata_rows,
        max_metadata_bytes=args.max_metadata_bytes,
    )
    results = profiler.profile()
    if args.output:
        profiler.save(results, args.output)
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
