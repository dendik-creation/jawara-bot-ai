"""Wire contract for Operator Feedback (04_AI_and_ML/04_Datasets_and_Operator_Feedback.md).

No create/update request models here — feedback rows are only ever written
as a side effect of `PATCH /threats/{id}` with `action=CONFIRM|FALSE_POSITIVE`
(`app.services.feedback.record_feedback`), never directly by an operator.
"""

from typing import Literal

FeedbackType = Literal["CONFIRM", "FALSE_POSITIVE"]
