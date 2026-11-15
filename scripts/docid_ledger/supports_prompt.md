You are labeling which question constraints a search-result passage explicitly supports.

You are given: a question, its reference answer, a numbered list of constraints extracted from the question, and one search-result passage.

For each constraint, decide whether the passage itself explicitly states information that establishes that constraint for the entity or entities the question is about. The reference answer is provided only so you know which entity the question refers to. Do not use outside knowledge, and do not count your own inference across passages. If the passage only mentions related topics without establishing the constraint, it does not support it.

Return {"supports":[{"reason":"one short sentence in your own words","constraint_id":"C1"}]}. List only supported constraints. Return an empty list if none. Do not quote the passage.
