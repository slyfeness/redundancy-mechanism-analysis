An agent is researching the question below by issuing web searches. You are given its reasoning right before the current search, the current search query, and passages the agent has already seen in earlier search results, each with an ID.

Step 1. In one sentence, state what specific information this search is looking for: which entity (write "an unknown entity" if it is trying to find candidates) and which attribute or relation.

Step 2. Choose one category:
- "already_seen": every piece of information this search is looking for is already explicitly stated in one or more of the listed passages. List those passage IDs.
- "new_information": it is looking for information about a specific named entity, and at least part of that information is not stated in any listed passage.
- "new_candidate": it is trying to discover which entity satisfies some conditions, rather than checking a specific named entity.

Judge only by what the passages explicitly state, not by what the agent says it knows or has confirmed. It does not matter whether the agent noticed or remembers a passage. Do not use outside knowledge.

Return {"seeking":"one sentence","reason":"one short sentence","category":"already_seen","passage_ids":["P123"]}. passage_ids must be empty unless category is "already_seen".
