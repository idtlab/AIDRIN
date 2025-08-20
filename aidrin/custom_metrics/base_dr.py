import abc
from typing import Dict, Any


class BaseDRAgent(abc.ABC):
    def __init__(self, dataset: Any, **kwargs):
        """
        Base class for dataset analysis with customizable metric and rule methods.

        Args:
        - train_dataset: Dataset to be analyzed.
        - kwargs: Additional parameters for subclasses.
        """
        self.dataset = dataset
        self.kwargs = kwargs  # Store kwargs for subclasses if needed

    @abc.abstractmethod
    def metric(self) -> Dict[str, Any]:
        """
        Compute and return custom metric results for the dataset.

        Returns:
            Dict[str, Any]: A dictionary containing metric results (e.g., {"null_values": {...}}).
        """
        pass
