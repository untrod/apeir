"""Repository discovery and deterministic test selection."""

from __future__ import annotations

from pathlib import Path

from nous_runtime.code_assistant.models import RepositoryProfile


class RepositoryAnalyzer:
    LANGUAGE_BY_SUFFIX = {".py": "python", ".js": "javascript", ".ts": "typescript", ".java": "java", ".rs": "rust", ".go": "go", ".kt": "kotlin", ".cs": "csharp"}
    IGNORED = {".git", ".nous", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}

    def analyze(self, root: str | Path) -> RepositoryProfile:
        workspace = Path(root).resolve()
        if not workspace.is_dir():
            raise ValueError("repository root must exist")
        files: list[str] = []
        languages: set[str] = set()
        for path in workspace.rglob("*"):
            if not path.is_file() or any(part in self.IGNORED for part in path.relative_to(workspace).parts):
                continue
            relative = path.relative_to(workspace).as_posix()
            files.append(relative)
            language = self.LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
            if language:
                languages.add(language)
            if len(files) >= 20_000:
                break
        dependency_names = {"pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts"}
        dependencies = tuple(sorted(item for item in files if Path(item).name in dependency_names))
        toolchains: set[str] = set()
        if any(Path(item).name in {"pyproject.toml", "requirements.txt"} for item in dependencies):
            toolchains.add("python")
        if any(Path(item).name == "package.json" for item in dependencies):
            toolchains.add("node")
        if any(Path(item).name == "Cargo.toml" for item in dependencies):
            toolchains.add("cargo")
        if any(Path(item).name == "go.mod" for item in dependencies):
            toolchains.add("go")
        return RepositoryProfile(str(workspace), tuple(sorted(languages)), tuple(sorted(toolchains)), tuple(sorted(files)), dependencies)

    @staticmethod
    def select_tests(profile: RepositoryProfile) -> tuple[tuple[str, ...], ...]:
        commands: list[tuple[str, ...]] = []
        if "python" in profile.toolchains:
            commands.append(("python", "-m", "pytest", "-q"))
        if "node" in profile.toolchains:
            commands.append(("npm", "test", "--", "--runInBand"))
        if "cargo" in profile.toolchains:
            commands.append(("cargo", "test"))
        if "go" in profile.toolchains:
            commands.append(("go", "test", "./..."))
        return tuple(commands)

    @staticmethod
    def select_static_analysis(profile: RepositoryProfile) -> tuple[tuple[str, ...], ...]:
        commands: list[tuple[str, ...]] = []
        if "python" in profile.toolchains:
            commands.append(("python", "-m", "ruff", "check", "."))
        if "cargo" in profile.toolchains:
            commands.append(("cargo", "clippy", "--", "-D", "warnings"))
        return tuple(commands)