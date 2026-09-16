# Unreal live acceptance checklist

## Before Play

- [ ] Run `scripts/run_office0_interaction.ps1` in a separate PowerShell window.
- [ ] Confirm the bridge log reports `server_started` and the XML is `office0_interaction.xml`.
- [ ] Build `ReplicaPhysicsTwinEditor` after closing the editor or pressing the Live Coding compile shortcut.
- [ ] Open `unreal\ReplicaPhysicsTwin.uproject` and press Play.

## What should be visible

- [ ] The room uses a readable warm-surface/cool-wall palette; collision debug outlines are hidden by default.
- [ ] `tissue_box` uses its semantic object mesh and rests on `desk_58`; it is not a black cube or magenta placeholder.
- [ ] `desk_organizer` uses its semantic object mesh and is orange on `desk_58`.
- [ ] `chair_4` uses its semantic object mesh and has MuJoCo floor contact.
- [ ] Selecting an object shows its id, size, mass, velocity, and contact count on screen.
- [ ] Contact count becomes non-zero when an object is resting on or touching another object.

## Interaction test

- [ ] Left click an object: one selection outline appears.
- [ ] Hold Shift and click the other two objects: all selected outlines appear.
- [ ] Shift+click only adds/removes selection; it never starts a grab.
- [ ] Normal click on a new object selects only it and starts a grab; normal drag on an already selected object moves the selected group through MuJoCo constraints.
- [ ] Drag one selected body into the other: the other dynamic body moves or rotates from MuJoCo contact.
- [ ] Release: the constraint is removed and the bodies continue under gravity, friction, and contact resolution.
- [ ] `R` resets; `T` lifts/drops the selected body; `P` pauses/resumes; `I` applies an impulse; `Esc` clears selection.

## Evidence to capture

- [ ] Play screen showing the three semantic meshes and the property overlay.
- [ ] Output Log lines containing `Connected to MuJoCo bridge` and command acknowledgements.
- [ ] `outputs/reports/physical_pipeline_validation.json` with `automated_passed=true`.
