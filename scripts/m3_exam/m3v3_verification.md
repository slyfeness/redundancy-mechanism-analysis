You are given a description of what a web search is trying to retrieve, and passages that were already seen earlier. Decide whether the core fact sought (this entity and this attribute or relation) is already explicitly stated in one or more of the passages. Ignore vague extras such as "details" or "more information". A related but different fact does not count. Do not use outside knowledge.

Return {"reason":"one short sentence","already_stated":true,"passage_ids":["P123"]}. passage_ids must be empty when already_stated is false.
