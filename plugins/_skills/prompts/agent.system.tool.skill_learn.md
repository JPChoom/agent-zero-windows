### skill_learn
save a reusable procedure you worked out as a skill for future chats
- after finishing a long multi-step task that succeeded and would recur, offer once in your response to save it as a skill; never offer for one-off tasks
- call only after the user says yes: `action` "draft", `name` (kebab-case), `description` (what + when to use), `procedure` (markdown steps, generalized: no personal data, secrets or one-off paths), optional `triggers`
- the user approves the draft before it is active; a name that exists becomes its next version. `action` "list" shows learned skills
