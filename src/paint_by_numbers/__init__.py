"""Turn any picture into an age-appropriate paint-by-numbers page.

>>> from paint_by_numbers import Settings, generate, render
>>> result = generate("photo.jpg", Settings.for_profile("6-8", style="cartoon"))  # doctest: +SKIP
>>> render(result).pdf()  # doctest: +SKIP
"""

from paint_by_numbers.pipeline import Result, Settings, generate
from paint_by_numbers.render import Rendered, render

__all__ = ["Rendered", "Result", "Settings", "generate", "render"]
__version__ = "0.1.0"
