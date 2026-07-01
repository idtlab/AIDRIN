import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _normalize_list(value: Optional[Any]) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]


@dataclass
class HeadlessConfig:
    file_path: str
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    metrics: Optional[List[str]] = field(default_factory=list)
    columns: Optional[List[str]] = field(default_factory=list)
    target_column: Optional[str] = None
    quasi_identifiers: Optional[List[str]] = field(default_factory=list)
    sensitive_column: Optional[str] = None
    epsilon: Optional[float] = None
    id_column: Optional[str] = None
    eval_columns: Optional[List[str]] = field(default_factory=list)
    distance_metric: Optional[str] = None
    cat_columns: Optional[List[str]] = field(default_factory=list)
    num_columns: Optional[List[str]] = field(default_factory=list)
    y_true_column: Optional[str] = None
    sensitive_attribute_column: Optional[str] = None
    save_images: Optional[bool] = None
    image_dir: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HeadlessConfig":
        incoming = dict(data or {})

        # Normalize keys: convert dashes to underscores and apply explicit aliases
        key_aliases = {
            "categorical-columns": "cat_columns",
            "numerical-columns": "num_columns",
            "target-column": "target_column",
            "y-true-column": "y_true_column",
            "quasi-identifiers": "quasi_identifiers",
            "sensitive-column": "sensitive_column",
            "sensitive-attribute-column": "sensitive_attribute_column",
            "eval-columns": "eval_columns",
            "id-column": "id_column",
            "distance-metric": "distance_metric",
            "file-path": "file_path",
            "file-type": "file_type",
            "file-name": "file_name",
            "image-dir": "image_dir",
            "save-images": "save_images",
        }

        normalized: Dict[str, Any] = {}
        for raw_key, value in incoming.items():
            key = raw_key.replace("-", "_")
            key = key_aliases.get(raw_key, key_aliases.get(key, key))
            normalized[key] = value

        # Normalize metric names to internal keys (replace dashes with underscores)
        if "metrics" in normalized and isinstance(normalized["metrics"], list):
            normalized["metrics"] = [str(m).replace("-", "_") for m in normalized["metrics"]]

        for key in (
            "metrics",
            "columns",
            "quasi_identifiers",
            "eval_columns",
            "cat_columns",
            "num_columns",
        ):
            if key in normalized:
                normalized[key] = _normalize_list(normalized[key])
        return cls(**normalized)

    @classmethod
    def from_json_file(cls, path: str) -> "HeadlessConfig":
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload)

    @classmethod
    def from_file(cls, path: str) -> "HeadlessConfig":
        ext = os.path.splitext(path)[1].lower()
        if ext in (".yaml", ".yml"):
            import yaml

            with open(path, encoding="utf-8") as handle:
                payload = yaml.safe_load(handle)
            return cls.from_dict(payload or {})
        return cls.from_json_file(path)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
