from inspect_ai.model import modelapi


@modelapi(name="harness")
def harness():
    from .provider import HarnessAPI

    return HarnessAPI
