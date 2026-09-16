"""Refusal messages a WDK site sends for a step that will not run."""

from __future__ import annotations

STALE_DATASET_REFUSAL = (
    r"""POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 """
    r"""(UNSPECIFIED): This step is not runnable for the following reasons: """
    r"""{"keyedErrors":{"bq_right_op_TranscriptRecordClasses_TranscriptRecordClass":"""
    r"""["The step referenced by ID '440118363' is not runnable because: """
    r"""{\n \"keyedErrors\": {\n \"samples_percentile_generic\": """
    r"""[\"At least one parameter that 'samples_percentile_generic' depends on """
    r"""is invalid or missing. Errors: \\n{\\n profileset_generic => Invalid """
    r"""value 'P. falciparum Su Strand Specific RNA Seq data - - Sense'.\\n}\\n\"],"""
    r"""\n \"profileset_generic\": [\"Invalid value """
    r"""'P. falciparum Su Strand Specific RNA Seq data - - Sense'.\"]\n },\n """
    r"""\"validationLevel\": \"RUNNABLE\", \"validationStatus\": \"FAILED\", """
    r"""\"errors\": []\n}"]},"validationLevel":"RUNNABLE","""
    r""""validationStatus":"FAILED","errors":[]}"""
)
"""The refusal a saved strategy got when a step named a dataset value the site dropped."""

STALE_VALUE = "P. falciparum Su Strand Specific RNA Seq data - - Sense"

OWN_VALUE_REFUSAL = (
    "POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 "
    "(UNSPECIFIED): This step is not runnable for the following reasons: "
    '{"keyedErrors":{"organism":["Invalid value \'Plasmodium berghei ANKA\'."]},'
    '"validationLevel":"RUNNABLE","validationStatus":"FAILED","errors":[]}'
)

FIRST_INPUT_REFUSAL = (
    "POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 "
    "(UNSPECIFIED): This step is not runnable for the following reasons: "
    '{"keyedErrors":{"bq_left_op_TranscriptRecordClasses_TranscriptRecordClass":'
    "[\"The step referenced by ID '440118363' is not runnable because: "
    '{\\"keyedErrors\\":{\\"organism\\":[\\"Invalid value '
    '\'Plasmodium berghei ANKA\'.\\"]},\\"validationLevel\\":\\"RUNNABLE\\",'
    '\\"validationStatus\\":\\"FAILED\\"}"]},'
    '"validationLevel":"RUNNABLE","validationStatus":"FAILED","errors":[]}'
)

UNREADABLE_REFUSAL = (
    "POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 "
    "(UNSPECIFIED): This step is not runnable for the following reasons: "
    '{"keyedErrors":{"samples_fold_change_generic":'
    '["The referenced result is no longer available."]},'
    '"validationLevel":"RUNNABLE","validationStatus":"FAILED","errors":[]}'
)

NOT_A_VALIDATION_REFUSAL = (
    "GET /users/1202189953/steps/440118373 -> HTTP 404: "
    '{"status":"not-found","message":"Step 440118373 not found."}'
)

MARKUP_VALUE_REFUSAL = (
    "POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 "
    "(UNSPECIFIED): This step is not runnable for the following reasons: "
    '{"keyedErrors":{"incoming":'
    '["Invalid value \'{\\"entityId\\":\\"OBI_0002695\\"}\'."]},'
    '"validationLevel":"RUNNABLE","validationStatus":"FAILED","errors":[]}'
)

TRANSFORM_INPUT_REFUSAL = (
    "POST /users/1202189953/steps/440118373/reports/standard -> HTTP 422 "
    "(UNSPECIFIED): This step is not runnable for the following reasons: "
    '{"keyedErrors":{"gene_result":'
    "[\"The step referenced by ID '440118363' is not runnable because: "
    '{\\"keyedErrors\\":{\\"organism\\":[\\"Invalid value '
    '\'Plasmodium berghei ANKA\'.\\"]},\\"validationLevel\\":\\"RUNNABLE\\",'
    '\\"validationStatus\\":\\"FAILED\\"}"]},'
    '"validationLevel":"RUNNABLE","validationStatus":"FAILED","errors":[]}'
)
