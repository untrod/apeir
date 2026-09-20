"""Controlled software-engineering workflow built on Agent adapters."""

from nous_runtime.code_assistant.models import CodeAssistantResult, CodeChangePlan, RepositoryProfile
from nous_runtime.code_assistant.patch import PatchScopeError, changed_paths_from_diff, validate_diff_scope
from nous_runtime.code_assistant.repository import RepositoryAnalyzer
from nous_runtime.code_assistant.service import CodeAssistant, CodingAgentAdapter

__all__ = ["CodeAssistant", "CodeAssistantResult", "CodeChangePlan", "CodingAgentAdapter", "PatchScopeError", "RepositoryAnalyzer", "RepositoryProfile", "changed_paths_from_diff", "validate_diff_scope"]