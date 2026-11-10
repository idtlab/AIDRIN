"""OpenTelemetry provider construction.

Split out from ``aidrin.telemetry`` so the public API stays readable: everything
here is concerned with building a ``TracerProvider`` and choosing an exporter,
and every import is inside a function so the package costs nothing when the
``[telemetry]`` extra is not installed.
"""

import logging
import os

logger = logging.getLogger(__name__)


def build_provider(service_name=None):
    """Return a configured ``TracerProvider``, or ``None`` if OTel is absent.

    Exporter selection follows the OpenTelemetry environment conventions:
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` sends spans to a collector, and without it
    spans go to the console so a developer can see them.
    """
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        logger.debug("OpenTelemetry packages not installed — telemetry disabled")
        return None

    service_name = service_name or os.environ.get("OTEL_SERVICE_NAME", "aidrin")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            logger.info("OpenTelemetry: exporting traces to %s", endpoint)
        except ImportError:
            logger.warning(
                "OpenTelemetry OTLP exporter not installed — traces will not be exported"
            )
    else:
        try:
            from opentelemetry.sdk.trace.export import (
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )

            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info(
                "OpenTelemetry: exporting traces to console "
                "(set OTEL_EXPORTER_OTLP_ENDPOINT for production)"
            )
        except ImportError:
            pass

    return provider
