# -*- coding: utf-8 -*-
"""Public version re-export.

Import this everywhere version is needed:
    from nous_runtime.version import __version__

The canonical version lives in `nous_runtime._version`. This module
exists for backward compatibility — all existing import paths continue
to work unchanged.
"""

from nous_runtime._version import __version__  # noqa: F401
