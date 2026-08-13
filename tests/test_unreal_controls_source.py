from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/MuJoCoBridgeDemoPlayerController.cpp"
GAME_MODE_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/MuJoCoBridgeDemoGameMode.cpp"
OFFICE_VISUAL_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/ReplicaOfficeVisualActor.cpp"
BRIDGE_ACTOR_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/MuJoCoBridgeDemoActor.cpp"


def test_unreal_controller_exposes_free_camera_controls() -> None:
    source = CONTROLLER_CPP.read_text(encoding="utf-8")

    assert "GetInputMouseDelta" in source
    assert "HandleCameraLookPressed" in source
    assert "HandleCameraLookReleased" in source
    assert "UpdateFreeCamera" in source
    assert "ActivateReplicaCamera" in source
    assert "SetViewTarget" in source
    for key in ("EKeys::W", "EKeys::A", "EKeys::S", "EKeys::D", "EKeys::Q", "EKeys::E"):
        assert key in source


def test_initial_camera_stays_inside_room_instead_of_rear_wall() -> None:
    source = GAME_MODE_CPP.read_text(encoding="utf-8")

    assert "ComputeReplicaCameraFrame" in source
    assert "PresentationBounds" in source
    assert "SceneBoundsMinCm" in source
    assert "SceneBoundsMaxCm" in source
    assert "recommended_distance_m" in source
    assert "InitialLocationCm" in source
    assert "SetFieldOfView(72.0f)" in source
    assert "RMB/WASD/QE" in source


def test_initial_camera_prioritizes_the_selected_objects_from_a_clear_interior_side() -> None:
    source = GAME_MODE_CPP.read_text(encoding="utf-8")

    # The full-room AABB is useful for safety limits, but it must not drive a
    # long-distance rear-wall shot.  The presentation camera should frame the
    # selected bike and garments from their own readable bounds.
    assert "DynamicMinimum" in source
    assert "DynamicMaximum" in source
    assert "DynamicSpanCm" in source
    assert "FVector(0.25f, -0.95f, 0.08f)" in source
    assert "FMath::Clamp(DynamicSpanCm * 1.12f, 220.0f, 360.0f)" in source
    assert "SetFieldOfView(72.0f)" in source
    assert "FVector(0.0f, 0.0f, -15.0f)" in source
    assert "RoomMarginCm = 100.0f" in source


def test_click_picking_uses_projected_mesh_bounds_not_only_actor_origin() -> None:
    source = CONTROLLER_CPP.read_text(encoding="utf-8")

    # Runtime visual meshes intentionally have no collision so they cannot be
    # selected by a physics trace.  Picking therefore has to project the
    # actual actor bounds into the viewport rather than asking whether the
    # cursor is close to one point at the actor origin.
    assert "GetComponentsBoundingBox(true)" in source
    assert "FBox WorldBounds" in source
    assert "ScreenMinX" in source
    assert "ScreenMaxY" in source
    assert "PickRadius" in source


def test_runtime_viewport_keeps_keyboard_and_mouse_input_on_the_game() -> None:
    source = CONTROLLER_CPP.read_text(encoding="utf-8")

    # The viewport must remain the input owner while the cursor is visible;
    # GameAndUI was allowing the editor/Slate layer to keep focus, so clicks
    # and WASD could be swallowed before reaching this controller.
    assert "FInputModeGameOnly InputMode" in source
    assert "SetConsumeCaptureMouseDown(false)" in source
    assert 'TEXT("Left click received' in source


def test_click_selects_but_only_a_real_drag_starts_physical_grab() -> None:
    source = CONTROLLER_CPP.read_text(encoding="utf-8")
    pressed_start = source.index("void AMuJoCoBridgeDemoPlayerController::HandleSelectPressed()")
    released_start = source.index("void AMuJoCoBridgeDemoPlayerController::HandleSelectReleased()")
    pressed = source[pressed_start:released_start]

    # A click is an inspection/selection action.  The MuJoCo command must be
    # delayed until the cursor has moved far enough to represent a push/drag.
    assert "bPendingMouseDrag" in source
    assert "DragStartThresholdPx" in source
    assert "TryStartMouseGrabIfDragged" in source
    assert "SendGrabBegin" not in pressed
    assert "IsInputKeyDown(EKeys::LeftMouseButton)" in source


def test_drag_plane_is_camera_facing_and_cloth_anchor_uses_physics_state() -> None:
    source = CONTROLLER_CPP.read_text(encoding="utf-8")

    # A horizontal Z plane becomes almost parallel to the view ray and caused
    # tiny cursor motion to turn into multi-metre target jumps.  The drag
    # plane must be fixed through the picked object and face the camera.
    assert "GrabPlaneNormalCm" in source
    assert "GrabPlaneStartPointCm" in source
    assert "FVector::DotProduct" in source
    assert "LatestState.PositionM" in source
    assert "GrabPlaneZCm" not in source


def test_interior_visuals_keep_source_winding_and_have_visible_material_fallbacks() -> None:
    office_source = OFFICE_VISUAL_CPP.read_text(encoding="utf-8")
    bridge_source = BRIDGE_ACTOR_CPP.read_text(encoding="utf-8")

    # The Replica room faces are already wound toward the room interior.  A
    # second normal inversion makes the walls receive almost no light.
    assert "const FVector SurfaceNormal = FaceNormal;" in office_source
    assert "const FVector InwardNormal = -FaceNormal;" not in office_source

    # Vertex colors are populated on the procedural meshes, so keep the
    # engine debug material as the first visible path when BasicShapeMaterial
    # is unavailable or unsuitable for the runtime renderer.
    assert office_source.index("VertexColorMaterial") < office_source.index("BaseMaterial")
    assert bridge_source.index("VertexColorMaterial") < bridge_source.index("ColorMaterial")
