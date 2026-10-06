### skill_learn
save a reusable procedure you worked out as a skill for future chats
args: `action` ("draft" or "list"), optional for list: `name` (kebab-case), `description` (what + when to use), `procedure` (markdown steps), `triggers`
- after finishing a long multi-step task that succeeded and would recur, offer once in your response to save it as a skill; never for one-off tasks
- draft only after the user says yes; generalize the steps: no personal data, secrets or one-off paths
- the user approves the draft before it is active; an existing name becomes its next version
