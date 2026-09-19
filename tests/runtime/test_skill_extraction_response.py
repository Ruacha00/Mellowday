"""A malformed extractor reply is a failure, not an empty candidate set."""
import pytest

from mellowday.runtime.skills.online_skill_evolution import online_ingest


@pytest.mark.anyio
@pytest.mark.parametrize("response", [
    '{"skills":[{"name":"planning","description":"Plan the day","instructions":"List appointments first.","evidence":"User corrected',
    "",
    "{}",
    '{"skills":null}',
    '{"skills":[{}]}',
])
async def test_invalid_extractor_output_is_reported_as_failed(response):
    calls = []

    async def query(system, payload):
        calls.append(system)
        return response

    result = await online_ingest(
        messages=[{"role": "user", "content": "From now on list fixed appointments before tasks."}],
        side_query=query,
    )
    assert result["action"] == "failed"
    assert result["ok"] is False and result["error"]
    assert result["error"].startswith("SkillExtractionResponseError:")
    assert len(calls) == 1  # Invalid extraction must not reach the manager/write stage.


@pytest.mark.anyio
async def test_explicit_empty_candidates_still_mean_nothing_to_learn():
    async def query(system, payload):
        return '{"skills":[]}'

    result = await online_ingest(messages=[{"role": "user", "content": "Hello"}], side_query=query)
    assert result["ok"] is True and result["action"] == "none"
