---
type: Decision
title: Each image is the last stage of its own Dockerfile
description: Jenkins builds the two images with the VEuPathDB shared builder, which takes no target and reads only a semver tag, so each server has its own Dockerfile and a release tag is spelled in semver.
tags: [images, release, jenkins]
status: stable
---

# The choice

`Jenkinsfile` hands the shared VEuPathDB builder (`pipelib`) two images, and each
names one file: `Dockerfile` ends on the WDK server and `Dockerfile.research` ends on
the research server. The builder takes an image name, a build context, a Dockerfile
and build arguments, and builds the last stage of the file; it has no target. Every
stage before the last one is the same text in both files, which
`tests/unit/test_dockerfiles.py` holds.

The builder publishes a pushed tag only when the tag is semver, so a release tag is the
semver spelling of `__version__`. `README.md` states the spellings.

# What would prove it wrong

The premise is the builder's source at commit `0c8c4d21`. A builder that selects a
stage removes the reason for the second Dockerfile, and a builder that publishes a
PEP 440 tag removes the reason for the semver tag.

- [`Builder.groovy`](https://github.com/VEuPathDB/pipelib/blob/0c8c4d21e689a71ba53cecf18f8c79f86c5e4c59/src/org/veupathdb/lib/Builder.groovy):
  `buildContainers` (lines 161-181) passes the list of images to `executeBuild` (line
  172). `executeBuild` reads `name`, `path`, `dockerfile`, `publishBranches` and
  `buildArgs` for each image (lines 193-201). `runPodBuild` (lines 308-347) passes `-f`
  for a Dockerfile other than `Dockerfile` (lines 334-336) and never passes `--target`.
  `parseTag` (lines 371-412) gives a tag to publish only when the tag matches one of its
  two semver patterns (lines 389 and 406).
- [`DockerConfig.groovy`](https://github.com/VEuPathDB/pipelib/blob/0c8c4d21e689a71ba53cecf18f8c79f86c5e4c59/src/org/veupathdb/lib/DockerConfig.groovy):
  the fields of one image (lines 11-16), with no target among them.

# What was rejected

**One Dockerfile with a `research` target.** The builder cannot select it, so the
research image would never be built.

**One Dockerfile whose last stage a build argument selects.** The builder passes build
arguments, but an image would then be decided by an argument outside the file, and a
build without the argument would produce the WDK server under any name.

**A research Dockerfile that starts from the published WDK image.** The two builds
would depend on their order, and the research image would carry the catalog snapshots
and the migration chain it never reads.

**Keeping PEP 440 tags and translating them in the build.** The tag patterns belong to
the shared builder, which every VEuPathDB service uses, not to this repository.

# The cost

The install stage is written twice. The test fails on the first difference between the
two copies, so an edit to one is made in both.
