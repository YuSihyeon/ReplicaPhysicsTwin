from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTOR_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/MuJoCoBridgeDemoActor.cpp"
OFFICE_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/ReplicaOfficeVisualActor.cpp"
MESH_FORMAT_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/ReplicaMeshFormat.cpp"
GAME_MODE_CPP = PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Private/Bridge/MuJoCoBridgeDemoGameMode.cpp"


def test_unreal_mesh_loaders_support_replica_cad_colored_rptmesh2() -> None:
    actor = ACTOR_CPP.read_text(encoding="utf-8")
    office = OFFICE_CPP.read_text(encoding="utf-8")

    mesh_format = MESH_FORMAT_CPP.read_text(encoding="utf-8")
    assert "RPTMESH2" in actor
    assert "RPTMESH2" in office
    assert "VertexColors" in mesh_format
    assert "CreateMeshSection" in mesh_format


def test_unreal_game_mode_uses_replica_cad_manifest_and_paths() -> None:
    source = GAME_MODE_CPP.read_text(encoding="utf-8")

    assert "replica_cad_interaction.json" in source
    assert "visual_mesh_file" in source
    assert "size_m" in source
    assert "../outputs/metadata/office0_interaction.json" not in source


def test_replica_office_visual_defaults_to_compiled_replica_cad_scene() -> None:
    header = (PROJECT_ROOT / "unreal/Source/ReplicaPhysicsTwin/Public/Bridge/ReplicaOfficeVisualActor.h").read_text(
        encoding="utf-8"
    )

    assert "../outputs/replica_cad/meshes/replica_cad_scene.rptmesh" in header
