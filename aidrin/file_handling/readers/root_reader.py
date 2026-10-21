from aidrin.file_handling.readers.structured import (
    INVENTORY_UNSUPPORTED,
    InventoryResult,
    StructuredFileReader,
    make_inventory,
)


class rootReader(StructuredFileReader):
    """ROOT file reader (scaffold). v1 will support TTrees only via uproot."""

    def inventory(self) -> InventoryResult:
        return make_inventory(INVENTORY_UNSUPPORTED)

    def read(self):
        self.logger.warning("ROOT read is not implemented yet.")
        return None
