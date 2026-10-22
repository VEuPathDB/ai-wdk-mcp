---
type: Decision
title: A served result validates its own dump
description: Every model a served tool returns validates the JSON its by-alias dump writes, so a host can store a tool result and read it back; a field read from a site column under another name lists its dump alias beside that column, a field that decodes a site value also takes the value it dumps, and why separate row models, a changed wire and a package alias policy were rejected.
tags: [payloads, audit, pydantic]
status: stable
---

# The choice

A host stores a tool result as `model_dump(by_alias=True, mode="json")` and reads it back
with `model_validate`. Every model a served tool returns accepts that dump and gives back
an equal instance.

The served models are `CamelModel`s, which dump each field under its camelCase alias and
validate by that alias or by the field name. A field that sets `validation_alias` to read a
site column replaces the camelCase alias for validation, so it dumps a key it does not
read when its name is not one word. Such a field names both keys:
`Field(validation_alias=AliasChoices("<site column>", "<camelCase alias>"))`. A field whose
name is one word dumps under its name and needs nothing more. A field that decodes a site
value with a `BeforeValidator` also takes the value it dumps.

The fix touched two models in `veupathdb_mcp/audit/evidence.py`. `Linkout.external_id`
reads `ext_id` or `externalId`. `GenomeProvenance.record_id`, `reference_strain` and
`ncbi_taxon` read `source_id`, `is_reference_strain` and `ncbi_tax_id`, or their
camelCase aliases, and `reference_strain` takes the site's `yes` or `no` or the boolean it
dumps.

# What was rejected

**A private row model beside each served model.** `_PdbRow` and `_PeptideRow` exist
because their rows are grouped into fewer served values. A copy of `Linkout` and of
`GenomeProvenance` that only renames columns adds two classes and a field-by-field copy
for the four fields that needed one more alias.

**Serving the site's column names.** `externalId` and `recordId` are on the wire today,
and a host reads them. A changed key is a breaking change to every stored result.

**One alias policy for the package, such as an alias generator that adds the field name
and a site name to every field.** The camelCase alias and the field name are already read
for every field without a `validation_alias`, so a package policy changes nothing there.
For the fields that read a site column, the site name is not derivable from the field
name, so each field still names it.

# What would prove this wrong

`tests/unit/test_served_results_round_trip.py`: for every tool of both servers, every model
its return type reaches reads the key it dumps each field under, and the recorded results
of the thirteen gene-model tools that have recordings (the PIGA, K13, GLO1 and DMAW
evidence among them) validate their own dump to an equal instance.
