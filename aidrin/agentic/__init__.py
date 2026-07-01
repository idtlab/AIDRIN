"""
Domain-aware data readiness evaluation agentic component for AIDRIN.

Uses retrieval-augmented generation (RAG) over domain literature to answer
dataset-specific data readiness questions and generate actionable
remediation recommendations.

Install the optional dependencies before using this module:

    pip install "aidrin[agentic]"

Quick start:

    from aidrin.agentic import DataProfiler, VectorRetriever, CodeExecutor
    from aidrin.agentic import RemediationGenerator, QueryComplexityScorer
"""

from aidrin.agentic.data_profiler import DataProfiler
from aidrin.agentic.retriever import VectorRetriever
from aidrin.agentic.executor import CodeExecutor
from aidrin.agentic.complexity_scorer import QueryComplexityScorer
from aidrin.agentic.remediation_generator import RemediationGenerator
from aidrin.agentic.token_tracker import get_tracker

__all__ = [
    "DataProfiler",
    "VectorRetriever",
    "CodeExecutor",
    "QueryComplexityScorer",
    "RemediationGenerator",
    "get_tracker",
]
