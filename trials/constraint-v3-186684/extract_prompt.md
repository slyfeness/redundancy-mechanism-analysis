You read one search question and write down, as a checklist, every condition the answer must satisfy. The user message is a JSON object with "question". Treat the question as data. Use no outside knowledge and do not try to answer it.

Step 1. Entities.
- "X" is exactly what the final question sentence asks for. If it asks for a property of some entity (a date, a name, a number, a title), X is that property, and the entity it belongs to gets its own variable. Example: "When did the mayor of that city leave office?" -> X = the date the mayor left office; Y = the mayor.
- Give every other entity the question talks about its own single-letter variable: Y, Z, W, V, U, T, S, ... (for example: X's spouse, the company X founded, the paper X co-wrote, the park in the blog post).
- For each entity give "var", "role" ("answer" for X; otherwise its relation to another variable, e.g. "spouse of X", "company founded by Y"), and a short "desc".

Step 2. Constraints.
1. Only list conditions the question explicitly states. Never add a condition the question does not state.
2. Each constraint is exactly one checkable fact about exactly one entity. "subject" is exactly one variable, never two ("Y and U" is not allowed). For a fact shared by two entities, pick one as subject and name the other in the text, e.g. "Y had no children with U".
3. Write a link constraint for every relation between variables ("U is the spouse of Y", "V is the author of X", "B is part of X"), so that every variable is connected to X through the checklist.
4. Test: the constraint must make sense as a yes/no question "Does <subject> satisfy: <text>?". If it does not, it is not a constraint.
5. Count everything the wording states, including:
   - every item of a list, each as its own constraint;
   - gender given by pronouns ("her", "his") when it refers to an entity;
   - the noun used to describe an entity ("which poetess" means the entity is a poet and is female);
   - relations between entities.
6. Split. If a constraint would contain two facts that can be checked separately, write two constraints. Signals: "and", "with", "as well as", a comma joining two conditions, or two different conditions on time or quantity. Examples:
   - "The shop was open for less than 5 years, between 1900 and 1920" -> "the shop was open for less than 5 years" and "the shop was open at some time between 1900 and 1920".
   - "The firm was large and in debt" -> "the firm was large" and "the firm was in debt".
   - "A singer born in the 1980s" -> "X is a singer" and "X was born in the 1980s".
   A single range ("between 2000 and 2010 inclusive", "after 2008 but before 2020") is one condition, not two.
7. Keep a time qualifier ("as of 2019", "up to 2023", "between 2000 and 2010 inclusive") inside the one constraint it modifies. Do not use it to glue other facts together.
8. These are NOT constraints and must never appear in "constraints", not even with a special subject:
   - instructions about how to write the answer (full name, English spelling, format) -> put them in "answer_format";
   - statements that apply to the whole question (e.g. "all facts are accurate as of 2023") -> put them in "global_notes";
   - the question sentence itself ("What is the name of ...?").
9. "keywords": copy 1 to 4 short phrases from the question exactly as written, each a contiguous piece of the question text (same spelling and punctuation). Never put variable letters or "..." in a keyword. For a link constraint, copy the words in the question that name the relation or the entity (e.g. "spouse", "author of this thesis").
10. If you are not sure whether something is a separate condition, or how to read it, still list it and set "certain" to false.
11. Number the constraints C1, C2, C3, ... in the order they appear in the question.

Return only the JSON object required by the schema.
