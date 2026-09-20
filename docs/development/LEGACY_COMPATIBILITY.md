# Legacy Compatibility Spec

## Purpose

`nous_runtime.compat` is the temporary compatibility boundary between Nous Runtime 2.0 and the legacy core implementation.

Runtime modules must import legacy functionality through this package instead of importing `remote_terminal.nous_core` directly.

## Rules

- `nous_runtime` code outside `nous_runtime.compat` must not import `remote_terminal.nous_core`.
- Compatibility adapters must not add new behavior unless required to preserve an existing public path.
- Runtime-native replacements should be introduced outside the compatibility package.
- Once a runtime-native replacement exists, the corresponding compatibility adapter should be reduced or removed in a separate migration.

## Allowed Direct Legacy Imports

Direct legacy imports are allowed only in:

- `nous_runtime/compat/**`

## Regression Test

The import boundary is checked by:

- `tests/test_architecture/test_import_boundaries.py`

The test scans `nous_runtime/**/*.py` and fails on `remote_terminal.nous_core` references outside the compatibility package.

## Migration Path

1. Move direct imports behind `nous_runtime.compat`.
2. Add runtime-native implementations for one legacy module at a time.
3. Update runtime modules to use the native implementation.
4. Keep compatibility shims only for older public paths.
5. Remove unused compatibility adapters after tests confirm no references remain.
