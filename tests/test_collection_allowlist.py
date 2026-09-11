from unittest.mock import patch

import pytest

from app.config import Settings
from app.models import RagRequest
from app.workflow import AuthorizedRagWorkflow


def request(collection, policies=None):
    return RagRequest(
        projectId="OTHER",
        question="What is OPS-72 status?",
        collectionName=collection,
        accessPolicyIds=policies if policies is not None else ["project:OTHER"],
    )


@pytest.mark.parametrize("collection", ["project-intelligence", "jira-stage-generic-release"])
def test_explicit_collection_routes_reach_project_validating_retriever(collection):
    settings = Settings(additional_chroma_collections=("jira-stage-generic-release",))
    with patch(
        "app.workflow.ChromaAccessRetriever.create", side_effect=RuntimeError("retriever boundary")
    ) as create:
        with pytest.raises(RuntimeError, match="retriever boundary"):
            AuthorizedRagWorkflow(settings, request(collection))
        assert create.call_args.kwargs["collection_name"] == collection
        assert create.call_args.kwargs["project_id"] == "OTHER"
        assert create.call_args.kwargs["access_policy_ids"] == ("project:OTHER",)


def test_unlisted_collection_and_unauthorized_project_fail_before_retrieval():
    settings = Settings(additional_chroma_collections=("jira-stage-generic-release",))
    with patch("app.workflow.ChromaAccessRetriever.create") as create:
        with pytest.raises(ValueError, match="configured Chroma"):
            AuthorizedRagWorkflow(settings, request("jira-stage-unlisted"))
        with pytest.raises(PermissionError):
            AuthorizedRagWorkflow(
                settings, request("jira-stage-generic-release", ["project:DIFFERENT"])
            )
        create.assert_not_called()
