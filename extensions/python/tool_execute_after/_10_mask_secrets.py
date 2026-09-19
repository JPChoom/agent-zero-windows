from helpers.extension import Extension
from helpers.secrets import get_secrets_manager
from helpers.tool import Response


class MaskToolSecrets(Extension):
    # Security control: if masking crashes, a secret could reach the
    # model/log unmasked. Fail-open here is worse than aborting the turn.
    FAIL_LOUD = True

    async def execute(self, response: Response | None = None, **kwargs):
        if not self.agent:
            return

        if not response:
            return
        secrets_mgr = get_secrets_manager(self.agent.context)
        response.message = secrets_mgr.mask_values(response.message)
