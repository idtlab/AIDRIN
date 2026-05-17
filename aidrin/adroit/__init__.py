"""
ADROIT — Agentic Data Readiness via Orchestrated Intelligent Toolkit.

An LLM-powered data readiness agent bundled with AIDRIN. ADROIT uses
retrieval-augmented generation (RAG) over domain literature to answer
dataset-specific data readiness questions and generate actionable
remediation recommendations.

Install the optional dependencies before using this module:

    pip install "aidrin[adroit]"

Quick start:

    from aidrin.adroit import DataProfiler, VectorRetriever, CodeExecutor
    from aidrin.adroit import RemediationGenerator, QueryComplexityScorer
"""

from aidrin.adroit.data_profiler import DataProfiler
from aidrin.adroit.retriever import VectorRetriever
from aidrin.adroit.executor import CodeExecutor
from aidrin.adroit.complexity_scorer import QueryComplexityScorer
from aidrin.adroit.remediation_generator import RemediationGenerator
from aidrin.adroit.token_tracker import get_tracker

__all__ = [
    "DataProfiler",
    "VectorRetriever",
    "CodeExecutor",
    "QueryComplexityScorer",
    "RemediationGenerator",
    "get_tracker",
]
