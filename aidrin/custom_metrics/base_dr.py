import abc
from typing import Dict, Any
import pandas as pd


class BaseDRAgent(abc.ABC):
    def __init__(self, dataset: Any, **kwargs):
        self.dataset = dataset
        self.kwargs = kwargs

    @abc.abstractmethod
    def metric(self, **kwargs) -> Dict[str, Any]:
        """Compute and return metric results as a dictionary."""
        pass

    @abc.abstractmethod
    def remedy(self, **kwargs) -> pd.DataFrame:
        """Apply remediation to the dataset and return the corrected DataFrame."""
        pass
