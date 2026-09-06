I stopped myself here: I attempted the same tool request ({{tool_name}}) {{count}} times in a row without making progress, so I'm ending this turn instead of continuing to retry.

Worth checking first: if those repeated calls had **empty or missing arguments**, the tool's description probably isn't telling the model what arguments it accepts. That is a tool-definition problem rather than a model problem, and neither retrying nor changing model settings will fix it.

Otherwise the model is likely struggling to produce a valid call for this request. Breaking the task into smaller steps, switching to a more capable model, or using the Tiny Local agent profile with a small local model often resolves it.
