import pytest

from hackathon26 import bedrock
from hackathon26.synthesis.gateway import BedrockModel
from hackathon26.synthesis.service import GuardrailNotConfigured


class Client:
    def __init__(self,reply=None): self.requests=[]; self.reply=reply
    def converse(self, **kwargs):
        self.requests.append(kwargs)
        if self.reply is not None: return self.reply
        return {"stopReason":"end_turn", "output":{"message":{"role":"assistant","content":[
            {"reasoningContent":{"reasoningText":{"text":"hidden","signature":"test"}}},
            {"text":'{"items":[]}'}]}},
            "trace":{"guardrail":{"inputAssessment":{"test-guardrail":{"contentPolicy":{"filters":[]}}},
                                  "outputAssessments":{"test-guardrail":[{"topicPolicy":{"topics":[]}}]}}}}


def test_guarded_call_attaches_config_tags_input_and_uses_shared_pacing(monkeypatch):
    client=Client(); slots=[]
    monkeypatch.setattr(bedrock,"_guarded_client",client,raising=False)
    monkeypatch.setattr(bedrock._limiter,"wait",lambda:slots.append(True))
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID","test-guardrail")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION","1")
    reply=BedrockModel().generate('{"findings":[]}')
    assert reply.text=='{"items":[]}'
    assert reply.guardrail_assessed is True
    assert slots==[True]
    request=client.requests[0]
    assert request["guardrailConfig"]=={"guardrailIdentifier":"test-guardrail","guardrailVersion":"1","trace":"enabled"}
    assert "guardContent" in request["messages"][0]["content"][0]
    assert "temperature" not in request["inferenceConfig"]


@pytest.mark.parametrize("version",["", "DRAFT", "0"])
def test_missing_or_unpublished_guardrail_never_calls_bedrock(monkeypatch,version):
    client=Client()
    monkeypatch.setattr(bedrock,"_guarded_client",client,raising=False)
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID","test-guardrail")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION",version)
    with pytest.raises(GuardrailNotConfigured): BedrockModel().generate("packet")
    assert client.requests==[]


def test_input_assessment_alone_does_not_confirm_guarded_output(monkeypatch):
    reply=Client().converse()
    del reply["trace"]["guardrail"]["outputAssessments"]
    client=Client(reply)
    monkeypatch.setattr(bedrock,"_guarded_client",client)
    monkeypatch.setattr(bedrock._limiter,"wait",lambda:None)
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID","test-guardrail")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION","1")
    assert BedrockModel().generate("packet").guardrail_assessed is False


def test_intervention_stop_reason_survives_missing_output(monkeypatch):
    monkeypatch.setattr(bedrock,"_guarded_client",Client({"stopReason":"guardrail_intervened"}))
    monkeypatch.setattr(bedrock._limiter,"wait",lambda:None)
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID","test-guardrail")
    monkeypatch.setenv("BEDROCK_GUARDRAIL_VERSION","1")
    assert BedrockModel().generate("packet").stop_reason=="guardrail_intervened"
