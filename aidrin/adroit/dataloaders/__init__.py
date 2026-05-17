"""
Built-in data loaders for ADROIT example use cases.

Each module exposes a ``load_dataset() -> pd.DataFrame`` function that can be
referenced in a YAML config as:

    paths:
      data_loader: "aidrin.adroit.dataloaders.<module>:load_dataset"

The loaders expect the corresponding dataset files to be present under a
``use_cases/`` directory at the root of the AIDRIN installation. Users can
write their own loaders following the same pattern and reference them via the
YAML ``paths.data_loader`` key.
"""
