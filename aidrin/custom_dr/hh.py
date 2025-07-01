from .base_dr import BaseDRAgent

from typing import Any
class hh(BaseDRAgent):
    def __init__(self, dataset: Any, **kwargs):
        # Initialize the parent class with dataset and additional arguments
        super().__init__(dataset, **kwargs)
        
        # Additional initialization logic can be added here if needed
        self.dataset = dataset  # Ensure dataset is initialized
        
    def metric(self):
        """
        Implement your custom metric logic here.
        Return a dictionary of results.
        """
        # Example:
        # return {
        #     "null_values": self.dataset.isnull().sum().to_dict()
        # }
        pass
    