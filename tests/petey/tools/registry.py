"""Small ToolSpec compatible with the fields exercised by this add-on."""


class ToolSpec:
    def __init__(self, **values):
        self.__dict__.update(values)
