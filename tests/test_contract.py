"""Shared response shape constraints for future application responses."""

import pytest
from pydantic import ValidationError

from app.observability.contracts import ServiceResponse


@pytest.mark.parametrize("outcome",["answer","clarify","refuse","empty_result"])
def test_required_response_fields(outcome: str) -> None:
    """Serialization retains null fields and a trace ID on every outcome."""
    response = ServiceResponse(outcome=outcome,value=None,metric_definition=None,sql=None)
    assert set(response.model_dump(mode="json")) == {"outcome","value","metric_definition","sql","trace_id"}
    assert response.trace_id


def test_unknown_outcome_and_missing_fields_rejected() -> None:
    """Do not permit invented outcomes or omitted nullable fields."""
    with pytest.raises(ValidationError):
        ServiceResponse(outcome="success",value=None,metric_definition=None,sql=None)
    with pytest.raises(ValidationError):
        ServiceResponse(outcome="clarify")
