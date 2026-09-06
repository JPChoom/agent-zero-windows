I stopped myself here: I produced the same response {{count}} times in a row without making progress, so I'm ending this turn instead of continuing to retry.

This usually means the model is looping - restating or rewriting the same answer without ever committing to a tool call. Breaking the request into smaller steps, or switching to a more capable model, usually resolves it; the Tiny Local agent profile is worth trying with a small local model.

If it repeats on a specific tool, check that tool's description states its arguments - a tool advertising none leaves the model with no valid call to make.
