# ReplicaCAD Physics Twin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current raw Replica office proxy scene with a reproducible ReplicaCAD-based pipeline whose selected real object assets retain their dataset geometry, convex collision geometry, authoritative mass, material metadata, and scene transforms in MuJoCo, while Unreal displays the same object geometry and allows inspection of the physical state.

**Architecture:** Download and validate the open ReplicaCAD dataset, parse its scene/object configuration and embedded GLB assets with a dependency-light converter, emit MuJoCo-compatible collision OBJ/MJCF plus Unreal-compatible colored mesh files and a scene manifest, then point the existing bridge/game mode at that manifest. ReplicaCAD remains the source of object geometry and mass; MuJoCo is authoritative for dynamics; Unreal is the visual/input client.

**Tech Stack:** Python 3.11, NumPy, MuJoCo, pytest, GLB/OBJ parsing implemented in the project, Unreal C++ procedural mesh loader, ReplicaCAD CC BY 4.0 assets.

## Global Constraints

- Preserve the existing raw Replica outputs and scripts; the new pipeline must be additive and selectable.
- Never represent a selected object only as an AABB or a generic cube. Use the dataset render mesh and convex collision asset.
- Use ReplicaCAD object-config mass values as authoritative. If inertia is derived because the dataset config does not provide it, record the derivation in the manifest.
- Keep object IDs, display names, source asset paths, mass, collision asset, and transform in one generated metadata file consumed by both MuJoCo and Unreal.
- Keep the first experiment small: scene `apt_0` and three dataset-native objects (`frl_apartment_box`, `frl_apartment_rack_01`, `frl_apartment_chair_01`). Do not label them as exact tissue/organizer assets unless the source asset has that identity.
- Include a dataset/license provenance report so the scene can be reproduced and attributed.

---

## Task 1: Dataset acquisition and source validation

- [x] Add a documented download command/script for the official `ai-habitat/ReplicaCAD_dataset` source.
- [x] Download or resume the interactive dataset into `data/raw/replica_cad`.
- [x] Validate `apt_0`, the FRL apartment stage, and the three selected object templates.
- [x] Fail with actionable diagnostics for missing GLB/config/collision files.

Verification: the validator reports all required assets, the exact source mass for the three templates, and the CC BY 4.0 provenance.

## Task 2: GLB conversion and coordinate adapter (tests first)

- [x] Add failing unit tests for parsing a minimal embedded GLB, material colors, triangle indices, node transforms, OBJ export, and `RPTMESH2` export.
- [x] Implement a stdlib/NumPy GLB reader sufficient for ReplicaCAD embedded geometry.
- [x] Implement explicit ReplicaCAD Y-up to MuJoCo Z-up transform and quaternion conversion.
- [x] Implement visual mesh conversion with per-vertex/material color and collision OBJ conversion.
- [x] Keep `RPTMESH1` compatibility for the existing raw Replica path.

Verification: converter tests pass and a converted real ReplicaCAD asset has nonzero geometry, expected bounds, and no fallback cube marker.

## Task 3: ReplicaCAD scene compiler (tests first)

- [x] Add failing tests for loading scene instances, exact masses, selected/static roles, convex collision paths, and generated MJCF structure.
- [x] Implement ReplicaCAD config/scene dataclasses and asset resolution.
- [x] Compile stable room-shell box proxies, all non-selected static scene objects, and the three selected dynamic bodies into MJCF.
- [x] Compute and record collision-bound-derived inertia only when absent from source config.
- [x] Record source-to-MuJoCo mass validation, source COM, full-scene presentation bounds, and mocap grab handles.
- [x] Emit `replica_cad_interaction.json`, converted meshes, collision OBJs, and a provenance report.

Verification: MuJoCo compiles the generated XML; selected bodies have free joints, dataset masses, convex collision meshes, and make contacts with the static stage/table.

## Task 4: Unreal visual/manifest integration

- [x] Add failing loader tests or byte-level checks for `RPTMESH2` color data and legacy `RPTMESH1` handling.
- [x] Extend the procedural mesh loader to consume `RPTMESH2` per-vertex colors/material colors.
- [x] Load the ReplicaCAD scene manifest and stage/static visual mesh in the Unreal level while retaining the existing bridge input path.
- [x] Remove the hardcoded office-0 asset assumptions from the new mode path.
- [x] Keep physics/debug lines off by default; expose a clear opt-in debug flag so red/yellow/green lines are not mistaken for scene geometry.

Verification: Unreal log shows ReplicaCAD stage and object mesh loads, no procedural cube fallback for the selected assets, and the scene displays recognizable geometry and non-uniform materials.

## Task 5: End-to-end physical interaction verification

- [x] Add a deterministic verification script: drop selected bodies onto the dataset stage and source table, and assert contact plus nontrivial motion.
- [x] Verify source masses and object-specific friction/restitution in the generated metadata.
- [x] Run the complete Python test suite and the physical verifier.
- [x] Rebuild/launch Unreal using the generated ReplicaCAD manifest and leave the result open for visual inspection.
- [x] Frame the full stage/environment from an inside-room camera position and keep free camera controls available.
- [x] Document the exact user test: click selects one object, Shift+click toggles additional objects, drag applies a finite force, and camera orbit uses the existing mouse mode.

Verification: automated tests pass, MuJoCo contact data is nonzero, object motion is not a simple vertical translation, and the Unreal runtime log contains no missing-asset or fallback errors.

## Task 6: Handoff

- [x] Record changed files, commands, dataset provenance, and known limitation that ReplicaCAD has dataset-native box/rack/chair assets rather than an exact tissue-box/desk-organizer pair.
- [x] Use the finishing-a-development-branch workflow after all verification is complete.
