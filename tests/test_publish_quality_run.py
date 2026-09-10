import sys

from evaluation import publish_quality_run


def test_failed_quality_run_has_no_child_annotations(monkeypatch) -> None:
    spans: list[tuple[str, dict[str, object]]] = []

    class SpanScope:
        def __init__(self, name, attributes):
            self.name = name
            self.attributes = attributes

        def __enter__(self):
            spans.append((self.name, self.attributes))
            return self

        def __exit__(self, *_args):
            return None

    class Tracer:
        def start_as_current_span(self, name, attributes):
            return SpanScope(name, attributes)

    class Provider:
        def get_tracer(self, _name):
            return Tracer()

        def force_flush(self):
            return None

        def shutdown(self):
            return None

    monkeypatch.setattr(
        publish_quality_run, "configure_openinference", lambda _settings: Provider()
    )
    monkeypatch.setattr(
        publish_quality_run,
        "publish_scores_to_phoenix",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failed runs must not publish score annotations")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_quality_run",
            "--status",
            "failed",
            "--failed-stage",
            "ragas",
            "--project-id",
            "T2.0",
            "--run-id",
            "run-1",
        ],
    )

    publish_quality_run.main()

    assert spans == [
        (
            "rag.quality.run",
            {
                "openinference.span.kind": "CHAIN",
                "quality.run_id": "run-1",
                "quality.project_id": "T2.0",
                "quality.status": "failed",
                "quality.failed_stage": "ragas",
                "quality.dataset_version": "1",
                "quality.commit_sha": "unknown",
                "auth.boundary": "project:T2.0",
            },
        )
    ]
