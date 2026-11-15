An agent is issuing a web search. You are given the end of its reasoning right before the search and the search query. Describe only what THIS search is trying to retrieve, based on the query words and the agent's stated purpose for this search. Do not guess the agent's overall goal or final answer.

Return {"seeking":"one sentence","entity":"the specific named entity this search is about, or null if it is trying to find which entity fits some conditions","attribute":"the attribute or relation of that entity being sought"}.
